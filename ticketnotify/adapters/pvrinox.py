"""PVR INOX booking platform adapter with live api3.pvrcinemas.com endpoints."""

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


class PvrInoxAdapter(PlatformAdapter):
    platform_name = "pvrinox"
    platform_label = "PVR INOX"
    supported_countries = ["in", "lk"]

    BASE_URL = "https://www.pvrcinemas.com"
    API_URL = "https://api3.pvrcinemas.com/api/v1"

    async def search_movie(
        self,
        title: str,
        location: Any,
    ) -> List[MovieMatch]:
        """Search movies in PVR INOX network."""
        codes = getattr(location, "platform_codes", None) or getattr(location, "platform_mappings", {}) or {}
        city_name = codes.get("pvrinox") or getattr(location, "city", "Bengaluru")
        url = f"{self.API_URL}/movies/nowshowing"
        params = {"city": city_name}

        try:
            headers = await session_manager.get_valid_headers("pvrinox", city_name)
            data = await http_client.get_json(url, params=params, headers=headers)
            movies: List[MovieMatch] = []
            if isinstance(data, dict):
                items = data.get("output", {}).get("movies", []) or data.get("movies", []) or data.get("data", [])
                for item in items:
                    m_id = str(item.get("id") or item.get("filmCode") or item.get("film_code") or "")
                    m_title = str(item.get("title") or item.get("filmName") or item.get("name") or "")
                    if not m_id or not m_title:
                        continue
                    if title.lower() in m_title.lower() or m_title.lower() in title.lower():
                        movies.append(
                            MovieMatch(
                                movie_id=m_id,
                                platform=self.platform_name,
                                title=m_title.strip(),
                                languages=item.get("languages", ["English", "Hindi"]),
                                formats=item.get("formats", ["2D", "IMAX", "4DX", "P[XL]"]),
                                poster_url=item.get("poster") or item.get("filmPosterUrl"),
                                release_date=item.get("releaseDate"),
                                url=f"{self.BASE_URL}/movies/{city_name.lower()}/{m_id}",
                                extra_metadata={"city_name": city_name},
                            )
                        )
            if movies:
                return movies
        except Exception as e:
            logger.warning(f"PVR INOX search API failed: {e}.")

        return []

    async def get_shows(
        self,
        movie_id: str,
        location: Any,
        target_date: Optional[str] = None,
    ) -> FetchResult:
        """Fetch showtimes from PVR INOX."""
        t0 = time.time()
        codes = getattr(location, "platform_codes", None) or getattr(location, "platform_mappings", {}) or {}
        city_name = codes.get("pvrinox") or getattr(location, "city", "Bengaluru")
        query_date = target_date or datetime.now().strftime("%Y-%m-%d")
        url = f"{self.API_URL}/booking/shows"
        params = {"filmCode": movie_id, "city": city_name, "date": query_date}

        try:
            headers = await session_manager.get_valid_headers("pvrinox", city_name)
            data = await http_client.get_json(url, params=params, headers=headers)
            shows = self._parse_pvr_shows(data, movie_id, city_name, query_date)
            elapsed_ms = (time.time() - t0) * 1000.0
            return FetchResult.ok(shows, latency_ms=elapsed_ms)
        except Exception as e:
            elapsed_ms = (time.time() - t0) * 1000.0
            logger.warning(f"PVR INOX get_shows failed: {e}.")
            return classify_fetch_error(e, latency_ms=elapsed_ms)

    def _parse_pvr_shows(self, data: Any, movie_id: str, city_name: str, query_date: str) -> List[Show]:
        shows: List[Show] = []
        if not isinstance(data, dict):
            return shows

        cinemas = data.get("output", {}).get("cinemas", []) or data.get("cinemas", []) or []
        for c in cinemas:
            c_name = c.get("cinemaName") or c.get("name") or "PVR Cinema"
            c_id = str(c.get("cinemaId") or c.get("id") or "PVR1")
            lat = float(c.get("lat")) if c.get("lat") else None
            lng = float(c.get("lng")) if c.get("lng") else None
            
            chain = "PVR"
            if "inox" in c_name.lower():
                chain = "INOX"

            for s in c.get("shows", []) or c.get("showTimes", []):
                s_time = s.get("showTime") or s.get("time") or "14:00"
                s_fmt = s.get("format") or s.get("screenType") or s.get("experience") or "2D"
                s_lang = s.get("language") or "English"
                avail = s.get("availableSeats")
                total = s.get("totalSeats")
                min_p = float(s.get("price") or s.get("minPrice") or 250.0)
                max_p = float(s.get("maxPrice") or min_p + 200.0)
                
                status = SeatStatus.AVAILABLE
                if avail is not None and total is not None and total > 0:
                    pct = (avail / total) * 100
                    if avail == 0:
                        status = SeatStatus.SOLD_OUT
                    elif pct < 15:
                        status = SeatStatus.ALMOST_FULL
                    elif pct < 35:
                        status = SeatStatus.FILLING_FAST
                elif s.get("status") in ("filling_fast", "almost_full", "sold_out"):
                    status = SeatStatus(s.get("status"))

                sid = f"pvrinox:{c_id}:{query_date}:{s_time}:{s_fmt}:{s_lang}".replace(" ", "_")
                booking_url = f"{self.BASE_URL}/buytickets/{movie_id}/{city_name.lower()}"

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
        """Fetch cinemas from PVR INOX within radius."""
        city_name = location.city or "Bengaluru"
        cinemas: List[Cinema] = []
        try:
            url = f"{self.API_URL}/cinemas/city"
            headers = await session_manager.get_valid_headers("pvrinox", city_name)
            data = await http_client.get_json(url, params={"city": city_name}, headers=headers)
            items = data.get("output", {}).get("cinemas", []) or data.get("cinemas", []) or []
            for item in items:
                c_id = str(item.get("cinemaId") or item.get("id") or "")
                c_name = str(item.get("cinemaName") or item.get("name") or "")
                lat = float(item.get("latitude")) if item.get("latitude") else None
                lng = float(item.get("longitude")) if item.get("longitude") else None
                dist = None
                if lat and lng and location.latitude and location.longitude:
                    dist = haversine_distance_km(location.latitude, location.longitude, lat, lng)
                    if dist > radius_km:
                        continue

                chain = "INOX" if "inox" in c_name.lower() else "PVR"
                cinemas.append(
                    Cinema(
                        cinema_id=c_id,
                        platform=self.platform_name,
                        name=c_name,
                        city=city_name,
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
            logger.warning(f"PVR live cinema fetch failed: {e}.")

        return cinemas

    async def get_seat_layout(self, show_id: str) -> Optional[Dict[str, Any]]:
        """Fetch seat layout from PVR INOX booking backend."""
        try:
            url = f"{self.API_URL}/booking/seatlayout"
            headers = await session_manager.get_valid_headers("pvrinox")
            return await http_client.get_json(url, params={"showId": show_id}, headers=headers)
        except Exception as e:
            logger.debug(f"PVR seat layout failed: {e}")
            return None

    async def health_check(self) -> bool:
        """Health check for PVR INOX endpoints."""
        try:
            headers = await session_manager.get_valid_headers("pvrinox")
            res = await http_client.get_json(f"{self.API_URL}/cinemas/city", params={"city": "Delhi"}, headers=headers)
            return bool(res)
        except Exception:
            return False
