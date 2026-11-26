"""District (by Zomato) booking platform adapter."""

import logging
import time
from datetime import datetime
from typing import List, Optional, Dict, Any

from ticketnotify.adapters.base import (
    PlatformAdapter,
    MovieMatch,
    Show,
    SeatStatus,
    Cinema,
    FetchResult,
    FetchStatus,
    classify_fetch_error,
)
from ticketnotify.adapters.http_client import http_client
from ticketnotify.adapters.session_manager import session_manager
from ticketnotify.location.models import NormalizedLocation
from ticketnotify.location.distance import haversine_distance_km

logger = logging.getLogger(__name__)


class DistrictAdapter(PlatformAdapter):
    platform_name = "district"
    platform_label = "District (by Zomato)"
    supported_countries = ["in", "ae"]

    BASE_URL = "https://www.district.in"
    API_URL = "https://www.district.in/api/v1"

    async def search_movie(
        self,
        title: str,
        location: Any,
    ) -> List[MovieMatch]:
        """Search movies on District (Zomato)."""
        codes = getattr(location, "platform_codes", None) or getattr(location, "platform_mappings", {}) or {}
        city_slug = codes.get("district") or getattr(location, "city", "bengaluru").lower()
        url = f"{self.API_URL}/movies/search"
        params = {"q": title, "city": city_slug}

        try:
            headers = await session_manager.get_valid_headers("district", city_slug)
            data = await http_client.get_json(url, params=params, headers=headers)
            movies: List[MovieMatch] = []
            if isinstance(data, dict):
                items = data.get("results", []) or data.get("movies", []) or data.get("data", [])
                for item in items:
                    m_id = str(item.get("id") or item.get("movieId") or "")
                    m_title = str(item.get("name") or item.get("title") or "")
                    if not m_id or not m_title:
                        continue
                    if title.lower() in m_title.lower() or m_title.lower() in title.lower():
                        movies.append(
                            MovieMatch(
                                movie_id=m_id,
                                platform=self.platform_name,
                                title=m_title.strip(),
                                languages=item.get("languages", ["English"]),
                                formats=item.get("formats", ["2D", "3D"]),
                                poster_url=item.get("poster") or item.get("thumbnail"),
                                release_date=item.get("releaseDate"),
                                url=f"{self.BASE_URL}/movies/{city_slug}/{m_id}",
                                extra_metadata={"city_slug": city_slug},
                            )
                        )
            if movies:
                return movies
        except Exception as e:
            logger.warning(f"District search API failed: {e}.")

        return []

    async def get_shows(
        self,
        movie_id: str,
        location: Any,
        target_date: Optional[str] = None,
    ) -> FetchResult:
        """Fetch shows on District."""
        t0 = time.time()
        codes = getattr(location, "platform_codes", None) or getattr(location, "platform_mappings", {}) or {}
        city_slug = codes.get("district") or getattr(location, "city", "bengaluru").lower()
        query_date = target_date or datetime.now().strftime("%Y-%m-%d")
        url = f"{self.API_URL}/movies/{movie_id}/shows"
        params = {"city": city_slug, "date": query_date}

        try:
            headers = await session_manager.get_valid_headers("district", city_slug)
            data = await http_client.get_json(url, params=params, headers=headers)
            shows = self._parse_district_shows(data, movie_id, city_slug, query_date)
            elapsed_ms = (time.time() - t0) * 1000.0
            return FetchResult.ok(shows, latency_ms=elapsed_ms)
        except Exception as e:
            elapsed_ms = (time.time() - t0) * 1000.0
            logger.warning(f"District get_shows failed: {e}.")
            return classify_fetch_error(e, latency_ms=elapsed_ms)

    def _parse_district_shows(self, data: Any, movie_id: str, city_slug: str, query_date: str) -> List[Show]:
        shows: List[Show] = []
        if not isinstance(data, dict):
            return shows

        venues = data.get("venues", []) or data.get("cinemas", []) or []
        for v in venues:
            c_name = v.get("name") or "Cinema"
            c_id = str(v.get("id") or "V1")
            lat = float(v.get("lat")) if v.get("lat") else None
            lng = float(v.get("lng")) if v.get("lng") else None

            chain = None
            for ch in ["PVR", "INOX", "Cinepolis", "Miraj", "MovieMax"]:
                if ch.lower() in c_name.lower():
                    chain = ch
                    break

            for s in v.get("shows", []) or v.get("slots", []) or []:
                s_time = s.get("time") or s.get("startTime") or "18:00"
                s_fmt = s.get("format") or "2D"
                s_lang = s.get("language") or "English"
                avail = s.get("availableSeats")
                total = s.get("totalSeats")
                min_p = float(s.get("price") or s.get("minPrice") or 250.0)
                max_p = float(s.get("maxPrice") or min_p + 150.0)

                status = SeatStatus.AVAILABLE
                if avail is not None and total is not None and total > 0:
                    pct = (avail / total) * 100
                    if avail == 0:
                        status = SeatStatus.SOLD_OUT
                    elif pct < 15:
                        status = SeatStatus.ALMOST_FULL
                    elif pct < 35:
                        status = SeatStatus.FILLING_FAST

                sid = f"district:{c_id}:{query_date}:{s_time}:{s_fmt}:{s_lang}".replace(" ", "_")
                booking_url = f"{self.BASE_URL}/movies/{city_slug}/{movie_id}"

                shows.append(
                    Show(
                        show_id=sid,
                        platform=self.platform_name,
                        movie_id=movie_id,
                        movie_title=s.get("movieTitle", "Movie"),
                        cinema_name=c_name,
                        cinema_id=c_id,
                        cinema_chain=chain,
                        latitude=lat,
                        longitude=lng,
                        date=query_date,
                        time=s_time,
                        format=s_fmt,
                        language=s_lang,
                        min_price=min_p,
                        max_price=max_p,
                        available_seats=avail,
                        total_seats=total,
                        seat_status=status,
                        booking_url=booking_url,
                    )
                )

        return shows

    async def get_cinemas(
        self,
        location: NormalizedLocation,
        radius_km: float = 10.0,
    ) -> List[Cinema]:
        """Fetch cinemas from District within radius."""
        city_slug = (location.city or "bengaluru").lower()
        cinemas: List[Cinema] = []
        try:
            url = f"{self.API_URL}/cinemas"
            headers = await session_manager.get_valid_headers("district", city_slug)
            data = await http_client.get_json(url, params={"city": city_slug}, headers=headers)
            items = data.get("cinemas", []) if isinstance(data, dict) else []
            for item in items:
                c_id = str(item.get("id") or "")
                c_name = str(item.get("name") or "")
                lat = float(item.get("latitude")) if item.get("latitude") else None
                lng = float(item.get("longitude")) if item.get("longitude") else None
                dist = None
                if lat and lng and location.latitude and location.longitude:
                    dist = haversine_distance_km(location.latitude, location.longitude, lat, lng)
                    if dist > radius_km:
                        continue

                chain = None
                for ch in ["PVR", "INOX", "Cinepolis", "Miraj", "MovieMax"]:
                    if ch.lower() in c_name.lower():
                        chain = ch
                        break

                cinemas.append(
                    Cinema(
                        cinema_id=c_id,
                        platform=self.platform_name,
                        name=c_name,
                        city=location.city or "Bengaluru",
                        latitude=lat,
                        longitude=lng,
                        chain=chain,
                        address=item.get("address"),
                        distance_km=round(dist, 2) if dist is not None else None,
                    )
                )
            if cinemas:
                return cinemas
        except Exception as e:
            logger.warning(f"District live cinema fetch failed: {e}.")

        return cinemas

    async def get_seat_layout(self, show_id: str) -> Optional[Dict[str, Any]]:
        """Fetch seat layout from District."""
        try:
            url = f"{self.API_URL}/shows/{show_id}/layout"
            headers = await session_manager.get_valid_headers("district")
            return await http_client.get_json(url, headers=headers)
        except Exception as e:
            logger.debug(f"District seat layout failed: {e}")
            return None

    async def health_check(self) -> bool:
        """Health check for District platform."""
        try:
            headers = await session_manager.get_valid_headers("district")
            res = await http_client.get_json(f"{self.API_URL}/movies/search", params={"q": "Avatar", "city": "bengaluru"}, headers=headers)
            return bool(res)
        except Exception:
            return False
