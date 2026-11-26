"""Worldwide Geocoding and Location Normalizer using OpenStreetMap Nominatim."""

import logging
import re
from typing import Optional, Dict, Any
import httpx

from ticketnotify.location.models import NormalizedLocation
from ticketnotify.location.matcher import map_location_to_platforms

logger = logging.getLogger(__name__)

# LRU/Memory cache for geocoding queries
_GEOCODE_CACHE: Dict[str, NormalizedLocation] = {}

# Built-in fallback database for key worldwide cities to ensure zero-failure operation
FALLBACK_CITIES = {
    "bengaluru": {"city": "Bengaluru", "country": "India", "country_code": "in", "state": "Karnataka", "lat": 12.9716, "lng": 77.5946},
    "bangalore": {"city": "Bengaluru", "country": "India", "country_code": "in", "state": "Karnataka", "lat": 12.9716, "lng": 77.5946},
    "mumbai": {"city": "Mumbai", "country": "India", "country_code": "in", "state": "Maharashtra", "lat": 19.0760, "lng": 72.8777},
    "delhi": {"city": "Delhi", "country": "India", "country_code": "in", "state": "Delhi", "lat": 28.6139, "lng": 77.2090},
    "new delhi": {"city": "Delhi", "country": "India", "country_code": "in", "state": "Delhi", "lat": 28.6139, "lng": 77.2090},
    "chennai": {"city": "Chennai", "country": "India", "country_code": "in", "state": "Tamil Nadu", "lat": 13.0827, "lng": 80.2707},
    "hyderabad": {"city": "Hyderabad", "country": "India", "country_code": "in", "state": "Telangana", "lat": 17.3850, "lng": 78.4867},
    "kolkata": {"city": "Kolkata", "country": "India", "country_code": "in", "state": "West Bengal", "lat": 22.5726, "lng": 88.3639},
    "pune": {"city": "Pune", "country": "India", "country_code": "in", "state": "Maharashtra", "lat": 18.5204, "lng": 73.8567},
    "kochi": {"city": "Kochi", "country": "India", "country_code": "in", "state": "Kerala", "lat": 9.9312, "lng": 76.2673},
    "coimbatore": {"city": "Coimbatore", "country": "India", "country_code": "in", "state": "Tamil Nadu", "lat": 11.0168, "lng": 76.9558},
    "madurai": {"city": "Madurai", "country": "India", "country_code": "in", "state": "Tamil Nadu", "lat": 9.9252, "lng": 78.1198},
    "dubai": {"city": "Dubai", "country": "United Arab Emirates", "country_code": "ae", "state": "Dubai", "lat": 25.2048, "lng": 55.2708},
    "london": {"city": "London", "country": "United Kingdom", "country_code": "gb", "state": "England", "lat": 51.5074, "lng": -0.1278},
    "new york": {"city": "New York", "country": "United States", "country_code": "us", "state": "New York", "lat": 40.7128, "lng": -74.0060},
    "los angeles": {"city": "Los Angeles", "country": "United States", "country_code": "us", "state": "California", "lat": 34.0522, "lng": -118.2437},
    "toronto": {"city": "Toronto", "country": "Canada", "country_code": "ca", "state": "Ontario", "lat": 43.6532, "lng": -79.3832},
    "singapore": {"city": "Singapore", "country": "Singapore", "country_code": "sg", "state": "Singapore", "lat": 1.3521, "lng": 103.8198},
    "sydney": {"city": "Sydney", "country": "Australia", "country_code": "au", "state": "New South Wales", "lat": -33.8688, "lng": 151.2093},
}


class LocationGeocoder:
    NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
    NOMINATIM_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
    USER_AGENT = "TicketNotifyBot/1.0 (+https://t.me/Tickets_NotifyBot)"

    def __init__(self, timeout: float = 8.0):
        self.timeout = timeout

    async def geocode(self, query: str) -> Optional[NormalizedLocation]:
        """Geocodes a query string (city name, pincode/zipcode, area, country)."""
        clean_query = query.strip()
        cache_key = clean_query.lower()

        if cache_key in _GEOCODE_CACHE:
            return _GEOCODE_CACHE[cache_key]

        # Check fallback table first for instant response
        if cache_key in FALLBACK_CITIES:
            data = FALLBACK_CITIES[cache_key]
            norm = NormalizedLocation(
                raw_query=clean_query,
                city=data["city"],
                country=data["country"],
                country_code=data["country_code"],
                state=data.get("state"),
                latitude=data["lat"],
                longitude=data["lng"],
                display_name=f"{data['city']}, {data['country']}",
            )
            norm = map_location_to_platforms(norm)
            _GEOCODE_CACHE[cache_key] = norm
            return norm

        # Try Nominatim search API
        try:
            headers = {"User-Agent": self.USER_AGENT}
            params = {
                "q": clean_query,
                "format": "jsonv2",
                "addressdetails": 1,
                "limit": 1,
            }
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(self.NOMINATIM_SEARCH_URL, params=params, headers=headers)
                if resp.status_code == 200:
                    results = resp.json()
                    if results and len(results) > 0:
                        norm = self._parse_nominatim_result(clean_query, results[0])
                        norm = map_location_to_platforms(norm)
                        _GEOCODE_CACHE[cache_key] = norm
                        return norm
        except Exception as e:
            logger.warning(f"Nominatim geocoding failed for '{clean_query}': {e}. Using fallback heuristic.")

        # Fallback heuristic: check if any known city substring matches query
        for city_key, data in FALLBACK_CITIES.items():
            if city_key in cache_key or cache_key in city_key:
                norm = NormalizedLocation(
                    raw_query=clean_query,
                    city=data["city"],
                    country=data["country"],
                    country_code=data["country_code"],
                    state=data.get("state"),
                    latitude=data["lat"],
                    longitude=data["lng"],
                    display_name=f"{data['city']}, {data['country']}",
                )
                norm = map_location_to_platforms(norm)
                _GEOCODE_CACHE[cache_key] = norm
                return norm

        # Default fallback if nothing resolved
        return None

    async def reverse_geocode(self, latitude: float, longitude: float) -> Optional[NormalizedLocation]:
        """Reverse geocodes GPS coordinates (e.g. from Telegram location share)."""
        cache_key = f"{round(latitude, 4)},{round(longitude, 4)}"
        if cache_key in _GEOCODE_CACHE:
            return _GEOCODE_CACHE[cache_key]

        try:
            headers = {"User-Agent": self.USER_AGENT}
            params = {
                "lat": latitude,
                "lon": longitude,
                "format": "jsonv2",
                "addressdetails": 1,
            }
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(self.NOMINATIM_REVERSE_URL, params=params, headers=headers)
                if resp.status_code == 200:
                    result = resp.json()
                    norm = self._parse_nominatim_result(f"GPS:{latitude},{longitude}", result)
                    norm = map_location_to_platforms(norm)
                    _GEOCODE_CACHE[cache_key] = norm
                    return norm
        except Exception as e:
            logger.warning(f"Reverse geocode failed for {latitude},{longitude}: {e}")

        # Fallback nearest city from fallback table
        nearest_city = None
        min_dist = float("inf")
        from ticketnotify.location.distance import haversine_distance_km
        for city_key, data in FALLBACK_CITIES.items():
            d = haversine_distance_km(latitude, longitude, data["lat"], data["lng"])
            if d < min_dist:
                min_dist = d
                nearest_city = data

        if nearest_city and min_dist < 200.0:
            norm = NormalizedLocation(
                raw_query=f"{latitude}, {longitude}",
                city=nearest_city["city"],
                country=nearest_city["country"],
                country_code=nearest_city["country_code"],
                state=nearest_city.get("state"),
                latitude=latitude,
                longitude=longitude,
                display_name=f"{nearest_city['city']}, {nearest_city['country']}",
            )
            norm = map_location_to_platforms(norm)
            _GEOCODE_CACHE[cache_key] = norm
            return norm

        return None

    def _parse_nominatim_result(self, raw_query: str, item: Dict[str, Any]) -> NormalizedLocation:
        address = item.get("address", {})
        city = (
            address.get("city")
            or address.get("town")
            or address.get("municipality")
            or address.get("suburb")
            or address.get("county")
            or item.get("name")
            or "Unknown"
        )
        country = address.get("country", "Unknown")
        country_code = address.get("country_code", "in").lower()
        state = address.get("state")
        lat = float(item.get("lat", 0.0))
        lng = float(item.get("lon", 0.0))
        display_name = item.get("display_name", f"{city}, {country}")

        return NormalizedLocation(
            raw_query=raw_query,
            city=city,
            country=country,
            country_code=country_code,
            state=state,
            latitude=lat,
            longitude=lng,
            display_name=display_name,
        )


geocoder = LocationGeocoder()
