"""Ticketnew booking platform adapter."""

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


class TicketnewAdapter(PlatformAdapter):
    platform_name = "ticketnew"
    platform_label = "Ticketnew"
    supported_countries = ["in"]

    BASE_URL = "https://www.ticketnew.com"
    API_URL = "https://apiv2.ticketnew.com/api"

    async def search_movie(
        self,
        title: str,
        location: Any,
    ) -> List[MovieMatch]:
        """Search movies on Ticketnew."""
        codes = getattr(location, "platform_codes", None) or getattr(location, "platform_mappings", {}) or {}
        city_slug = codes.get("ticketnew") or getattr(location, "city", "chennai").lower()
        url = f"{self.API_URL}/movies/search"
        params = {"query": title, "city": city_slug}

        try:
            headers = await session_manager.get_valid_headers("district", city_slug)
            data = await http_client.get_json(url, params=params, headers=headers)
            movies: List[MovieMatch] = []
            if isinstance(data, dict):
                items = data.get("movies", []) or data.get("data", [])
                for item in items:
                    m_id = str(item.get("id") or item.get("movieId") or "")
                    m_title = str(item.get("title") or item.get("name") or "")
                    if not m_id or not m_title:
                        continue
                    if title.lower() in m_title.lower() or m_title.lower() in title.lower():
                        movies.append(
                            MovieMatch(
                                movie_id=m_id,
                                platform=self.platform_name,
                                title=m_title.strip(),
                                languages=item.get("languages", ["Tamil"]),
                                formats=item.get("formats", ["2D"]),
                                poster_url=item.get("posterUrl") or item.get("image"),
                                release_date=item.get("releaseDate"),
                                url=f"{self.BASE_URL}/movies/{city_slug}/{m_id}",
                                extra_metadata={"city_slug": city_slug},
                            )
                        )
            if movies:
                return movies
        except Exception as e:
            logger.warning(f"Ticketnew search API failed: {e}.")

        return []

    async def get_shows(
        self,
        movie_id: str,
        location: Any,
        target_date: Optional[str] = None,
    ) -> FetchResult:
        """Fetch showtimes from Ticketnew."""
        t0 = time.time()
        codes = getattr(location, "platform_codes", None) or getattr(location, "platform_mappings", {}) or {}
        city_slug = codes.get("ticketnew") or getattr(location, "city", "chennai").lower()
        query_date = target_date or datetime.now().strftime("%Y-%m-%d")
        url = f"{self.API_URL}/shows"
        params = {"movieId": movie_id, "city": city_slug, "date": query_date}

        try:
            headers = await session_manager.get_valid_headers("district", city_slug)
            data = await http_client.get_json(url, params=params, headers=headers)
            shows = self._parse_ticketnew_shows(data, movie_id, city_slug, query_date)
            elapsed_ms = (time.time() - t0) * 1000.0
            return FetchResult.ok(shows, latency_ms=elapsed_ms)
        except Exception as e:
            elapsed_ms = (time.time() - t0) * 1000.0
            logger.warning(f"Ticketnew get_shows failed: {e}.")
            return classify_fetch_error(e, latency_ms=elapsed_ms)

    def _parse_ticketnew_shows(self, data: Any, movie_id: str, city_slug: str, query_date: str) -> List[Show]:
        shows: List[Show] = []
        if not isinstance(data, dict):
            return shows

        theatres = data.get("theatres", []) or data.get("cinemas", []) or []
        for t in theatres:
            t_name = t.get("name") or "Cinema"
            t_id = str(t.get("id") or "TN1")
            lat = float(t.get("lat")) if t.get("lat") else None
            lng = float(t.get("lng")) if t.get("lng") else None

            chain = None
            for ch in ["SPI", "PVR", "INOX", "AGS", "GK", "Vettri"]:
                if ch.lower() in t_name.lower():
                    chain = ch
                    break

            for s in t.get("shows", []) or []:
                s_time = s.get("showTime") or s.get("time") or "18:00"
                s_fmt = s.get("format") or "2D"
                s_lang = s.get("language") or "Tamil"
                avail = s.get("availableSeats")
                total = s.get("totalSeats")
                price = float(s.get("price") or 180.0)

                status = SeatStatus.AVAILABLE
                if avail is not None and total is not None and total > 0:
                    pct = (avail / total) * 100
                    if avail == 0:
                        status = SeatStatus.SOLD_OUT
                    elif pct < 15:
                        status = SeatStatus.ALMOST_FULL
                    elif pct < 35:
                        status = SeatStatus.FILLING_FAST

                sid = f"ticketnew:{t_id}:{query_date}:{s_time}:{s_fmt}:{s_lang}".replace(" ", "_")
                booking_url = f"{self.BASE_URL}/movies/{city_slug}/{movie_id}"

                shows.append(
                    Show(
                        show_id=sid,
                        platform=self.platform_name,
                        movie_id=movie_id,
                        movie_title=s.get("movieTitle", "Movie"),
                        cinema_name=t_name,
                        cinema_id=t_id,
                        cinema_chain=chain,
                        latitude=lat,
                        longitude=lng,
                        date=query_date,
                        time=s_time,
                        format=s_fmt,
                        language=s_lang,
                        min_price=price,
                        max_price=price + 80.0,
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
        """Fetch cinemas from Ticketnew within radius."""
        city_slug = (location.city or "chennai").lower()
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
                for ch in ["SPI", "PVR", "INOX", "AGS", "GK", "Vettri"]:
                    if ch.lower() in c_name.lower():
                        chain = ch
                        break

                cinemas.append(
                    Cinema(
                        cinema_id=c_id,
                        platform=self.platform_name,
                        name=c_name,
                        city=location.city or "Chennai",
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
            logger.warning(f"Ticketnew live cinema fetch failed: {e}.")

        return cinemas

    async def get_seat_layout(self, show_id: str) -> Optional[Dict[str, Any]]:
        """Fetch seat layout from Ticketnew."""
        try:
            url = f"{self.API_URL}/shows/{show_id}/layout"
            headers = await session_manager.get_valid_headers("district")
            return await http_client.get_json(url, headers=headers)
        except Exception as e:
            logger.debug(f"Ticketnew seat layout failed: {e}")
            return None

    async def health_check(self) -> bool:
        """Health check for Ticketnew endpoint."""
        try:
            res = await http_client.get_json(f"{self.API_URL}/movies", params={"city": "chennai"})
            return bool(res)
        except Exception:
            return False
