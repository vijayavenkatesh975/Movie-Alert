"""BookMyShow (BMS) booking platform adapter with live explore APIs and session manager."""

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


class BookMyShowAdapter(PlatformAdapter):
    platform_name = "bms"
    platform_label = "BookMyShow"
    supported_countries = ["in", "ae", "id", "lk"]

    BASE_URL = "https://in.bookmyshow.com"
    API_SEARCH_URL = "https://in.bookmyshow.com/serv/getData"
    API_EXPLORE_BASE = "https://in.bookmyshow.com/api/explore/v1"

    async def search_movie(
        self,
        title: str,
        location: Any,
    ) -> List[MovieMatch]:
        """Search for movies on BookMyShow using explore API with fallback."""
        codes = getattr(location, "platform_codes", None) or getattr(location, "platform_mappings", {}) or {}
        city_code = codes.get("bms") or "BANG"
        city_name = getattr(location, "city", "Bengaluru").lower()

        # 1. Try modern Explore API
        try:
            headers = await session_manager.get_valid_headers("bms", city_name)
            explore_url = f"{self.API_EXPLORE_BASE}/discover/movies-now-showing"
            params = {"regionCode": city_code}
            data = await http_client.get_json(explore_url, params=params, headers=headers)
            matches = self._parse_explore_movies(data, title, city_code)
            if matches:
                return matches
        except Exception as e:
            logger.debug(f"BMS explore API search failed: {e}. Trying legacy getData endpoint.")

        # 2. Try legacy getData endpoint
        params = {
            "cmd": "QUICKSEARCH",
            "type": "MOVIES",
            "q": title,
            "cc": city_code,
        }

        try:
            data = await http_client.get_json(self.API_SEARCH_URL, params=params)
            movies_list: List[MovieMatch] = []

            items = []
            if isinstance(data, dict):
                items = data.get("movies", {}).get("data", []) or data.get("data", [])
            elif isinstance(data, list):
                items = data

            for item in items:
                m_code = str(item.get("EventCode") or item.get("code") or item.get("id") or "")
                m_title = str(item.get("EventTitle") or item.get("title") or item.get("name") or "")
                
                if not m_code or not m_title:
                    continue

                if title.lower() in m_title.lower() or m_title.lower() in title.lower():
                    langs = item.get("EventLanguage", "").split(",") if item.get("EventLanguage") else []
                    formats = item.get("EventDimension", "").split(",") if item.get("EventDimension") else ["2D"]
                    poster = item.get("EventImageCode") or item.get("banner_url") or item.get("poster")

                    movies_list.append(
                        MovieMatch(
                            movie_id=m_code,
                            platform=self.platform_name,
                            title=m_title.strip(),
                            languages=[l.strip() for l in langs if l.strip()],
                            formats=[f.strip() for f in formats if f.strip()],
                            poster_url=f"https://assets-in.bmscdn.com/iedb/movies/images/mobile/thumbnail/xlarge/{poster}.jpg" if poster and not str(poster).startswith("http") else str(poster or ""),
                            release_date=item.get("EventReleaseDate"),
                            url=f"{self.BASE_URL}/movies/{city_code.lower()}/{m_code}",
                            extra_metadata={"city_code": city_code},
                        )
                    )

            if movies_list:
                return movies_list

        except Exception as e:
            logger.warning(f"BMS search API query failed: {e}.")

        return []

    def _parse_explore_movies(self, data: Any, query: str, city_code: str) -> List[MovieMatch]:
        matches: List[MovieMatch] = []
        if not isinstance(data, dict):
            return matches
        items = data.get("movies", []) or data.get("data", []) or []
        for item in items:
            code = str(item.get("eventCode") or item.get("code") or item.get("id") or "")
            name = str(item.get("eventTitle") or item.get("title") or "")
            if not code or not name:
                continue
            if query.lower() in name.lower() or name.lower() in query.lower():
                matches.append(
                    MovieMatch(
                        movie_id=code,
                        platform=self.platform_name,
                        title=name,
                        languages=item.get("languages", ["English"]),
                        formats=item.get("dimensions", ["2D"]),
                        poster_url=item.get("posterUrl"),
                        release_date=item.get("releaseDate"),
                        url=f"{self.BASE_URL}/buytickets/{code}/{city_code.lower()}",
                        extra_metadata={"city_code": city_code},
                    )
                )
        return matches

    async def get_shows(
        self,
        movie_id: str,
        location: Any,
        target_date: Optional[str] = None,
    ) -> FetchResult:
        """Fetch shows for a specific movie in the chosen location."""
        t0 = time.time()
        codes = getattr(location, "platform_codes", None) or getattr(location, "platform_mappings", {}) or {}
        city_code = codes.get("bms") or "BANG"
        city_name = getattr(location, "city", "Bengaluru").lower()
        query_date = target_date or datetime.now().strftime("%Y%m%d")
        formatted_date = query_date.replace("-", "")

        last_error: Optional[Exception] = None

        # 1. Try modern Explore shows endpoint
        try:
            headers = await session_manager.get_valid_headers("bms", city_name)
            explore_shows_url = f"{self.API_EXPLORE_BASE}/movies/{movie_id}/cinemas"
            params = {"date": formatted_date, "region": city_code}
            data = await http_client.get_json(explore_shows_url, params=params, headers=headers)
            shows = self._parse_bms_shows(data, movie_id, city_code, query_date)
            elapsed_ms = (time.time() - t0) * 1000.0
            return FetchResult.ok(shows, latency_ms=elapsed_ms)
        except Exception as e:
            last_error = e
            logger.debug(f"BMS explore shows endpoint failed: {e}. Trying legacy endpoint.")

        # 2. Try legacy endpoint
        params = {
            "cmd": "GETSHOWTIMESBYEVENT",
            "f": "json",
            "dc": formatted_date,
            "ec": movie_id,
            "cc": city_code,
        }

        try:
            data = await http_client.get_json(self.API_SEARCH_URL, params=params)
            shows = self._parse_bms_shows(data, movie_id, city_code, query_date)
            elapsed_ms = (time.time() - t0) * 1000.0
            return FetchResult.ok(shows, latency_ms=elapsed_ms)
        except Exception as e:
            last_error = e
            logger.warning(f"BMS legacy get_shows query failed: {e}.")

        elapsed_ms = (time.time() - t0) * 1000.0
        return classify_fetch_error(last_error or Exception("BMS endpoints returned no data"), latency_ms=elapsed_ms)

    def _parse_bms_shows(self, data: Any, movie_id: str, city_code: str, query_date: str) -> List[Show]:
        shows: List[Show] = []
        if not isinstance(data, dict):
            return shows

        cinemas = data.get("cinemas", []) or data.get("BookMyShow", {}).get("cinemas", [])
        for cinema in cinemas:
            c_name = cinema.get("VenueName") or cinema.get("name") or "Cinema"
            c_code = cinema.get("VenueCode") or cinema.get("code") or "V1"
            lat = float(cinema.get("Latitude")) if cinema.get("Latitude") else None
            lng = float(cinema.get("Longitude")) if cinema.get("Longitude") else None
            
            # Detect chain
            c_chain = None
            for chain in ["PVR", "INOX", "Cinepolis", "Miraj", "SPI", "MovieMax"]:
                if chain.lower() in c_name.lower():
                    c_chain = chain
                    break

            for session in cinema.get("Session", []) or cinema.get("shows", []):
                s_time = session.get("ShowTimeDisplay") or session.get("time") or "19:00"
                s_format = session.get("ScreenFormat") or session.get("dimension") or "2D"
                s_lang = session.get("Language") or "English"
                avail = session.get("AvailableSeats")
                total = session.get("TotalSeats")
                min_p = float(session.get("MinPrice") or 200.0)
                max_p = float(session.get("MaxPrice") or 450.0)
                
                # Determine seat status
                status = SeatStatus.AVAILABLE
                if avail is not None and total is not None and total > 0:
                    pct = (avail / total) * 100
                    if avail == 0:
                        status = SeatStatus.SOLD_OUT
                    elif pct < 15:
                        status = SeatStatus.ALMOST_FULL
                    elif pct < 40:
                        status = SeatStatus.FILLING_FAST
                elif session.get("Status") == "almost_full":
                    status = SeatStatus.ALMOST_FULL
                elif session.get("Status") == "filling_fast":
                    status = SeatStatus.FILLING_FAST

                unique_show_id = f"bms:{c_code}:{query_date}:{s_time}:{s_format}:{s_lang}".replace(" ", "_")
                booking_url = f"{self.BASE_URL}/buytickets/{movie_id}/{city_code.lower()}"

                shows.append(
                    Show(
                        show_id=unique_show_id,
                        platform=self.platform_name,
                        movie_id=movie_id,
                        movie_title=session.get("EventTitle", "Movie"),
                        cinema_name=c_name,
                        cinema_id=c_code,
                        cinema_chain=c_chain,
                        latitude=lat,
                        longitude=lng,
                        date=query_date,
                        time=s_time,
                        format=s_format,
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
        """Fetch cinemas operating in this location within the given radius."""
        codes = getattr(location, "platform_codes", None) or {}
        city_code = codes.get("bms") or "BANG"
        city_name = location.city.lower() if location.city else "bengaluru"

        cinemas: List[Cinema] = []
        try:
            headers = await session_manager.get_valid_headers("bms", city_name)
            url = f"{self.API_EXPLORE_BASE}/cinemas"
            params = {"regionCode": city_code}
            data = await http_client.get_json(url, params=params, headers=headers)
            items = data.get("cinemas", []) if isinstance(data, dict) else []
            for item in items:
                c_id = str(item.get("code") or item.get("id") or "")
                c_name = str(item.get("name") or "")
                lat = float(item.get("latitude")) if item.get("latitude") else None
                lng = float(item.get("longitude")) if item.get("longitude") else None
                dist = None
                if lat and lng and location.latitude and location.longitude:
                    dist = haversine_distance_km(location.latitude, location.longitude, lat, lng)
                    if dist > radius_km:
                        continue

                chain = None
                for ch in ["PVR", "INOX", "Cinepolis", "Miraj", "SPI", "MovieMax"]:
                    if ch.lower() in c_name.lower():
                        chain = ch
                        break

                cinemas.append(
                    Cinema(
                        cinema_id=c_id,
                        platform=self.platform_name,
                        name=c_name,
                        city=location.city,
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
            logger.warning(f"Could not fetch BMS live cinemas: {e}.")

        return cinemas

    async def get_seat_layout(self, show_id: str) -> Optional[Dict[str, Any]]:
        """Fetch seat layout dictionary for the specified show."""
        try:
            url = f"{self.API_EXPLORE_BASE}/shows/{show_id}/seat-layout"
            headers = await session_manager.get_valid_headers("bms")
            return await http_client.get_json(url, headers=headers)
        except Exception as e:
            logger.debug(f"BMS seat layout fetch failed: {e}")
            return None

    async def health_check(self) -> bool:
        """Health check for BMS endpoint."""
        try:
            res = await http_client.get_json(f"{self.API_EXPLORE_BASE}/discover/regions")
            return bool(res)
        except Exception:
            return False
