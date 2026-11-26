"""Template for adding a new cinema booking platform adapter.

To add a new platform (e.g. Fandango, AMC, Cineworld, Vox Cinemas, Reel Cinemas, Cinepolis):
1. Copy this file to `ticketnotify/adapters/{platform_name}.py`.
2. Define your class inheriting from `PlatformAdapter`.
3. Set `platform_name`, `platform_label`, and `supported_countries`.
4. Implement `search_movie`, `get_shows`, and `health_check`.
5. Register it in `ticketnotify/adapters/registry.py`.
"""

import logging
from datetime import datetime
from typing import List, Optional, Dict, Any

from ticketnotify.adapters.base import PlatformAdapter, MovieMatch, Show, SeatStatus
from ticketnotify.adapters.http_client import http_client
from ticketnotify.location.models import NormalizedLocation

logger = logging.getLogger(__name__)


class NewPlatformAdapterTemplate(PlatformAdapter):
    """
    Example implementation template for a new booking platform.
    Replace 'newplatform' with your platform key (e.g. 'fandango', 'amc', 'cineworld').
    """

    # 1. Unique lower-case identifier for this platform
    platform_name = "newplatform"

    # 2. User-facing display name
    platform_label = "New Platform"

    # 3. ISO 2-letter country codes where this platform operates (e.g. ['us'], ['gb'], ['ae'])
    supported_countries = ["us", "gb"]

    # 4. Base URLs / endpoints
    BASE_URL = "https://www.example-cinema.com"
    API_URL = "https://api.example-cinema.com/v1"

    async def search_movie(
        self,
        title: str,
        location: NormalizedLocation,
    ) -> List[MovieMatch]:
        """
        Search for movies by title in the user's location.

        Args:
            title: Movie title or keywords entered by the user.
            location: Normalized location object with city, country, lat, lng, and platform_codes.

        Returns:
            List[MovieMatch]: List of matched movies with ID, title, poster, formats, etc.
        """
        # Step A: Extract city/region identifier
        city = location.platform_codes.get(self.platform_name) or location.city

        # Step B: Call platform search endpoint
        url = f"{self.API_URL}/search"
        params = {"query": title, "city": city}

        try:
            data = await http_client.get_json(url, params=params)
            
            # Step C: Parse response into MovieMatch objects
            matches: List[MovieMatch] = []
            for item in data.get("results", []):
                movie_id = str(item.get("id"))
                movie_title = item.get("title")
                matches.append(
                    MovieMatch(
                        movie_id=movie_id,
                        platform=self.platform_name,
                        title=movie_title,
                        languages=item.get("languages", ["English"]),
                        formats=item.get("formats", ["2D"]),
                        poster_url=item.get("poster_url"),
                        release_date=item.get("release_date"),
                        url=f"{self.BASE_URL}/movie/{movie_id}",
                    )
                )
            return matches

        except Exception as err:
            logger.error(f"Error searching movie on {self.platform_name}: {err}")
            return []

    async def get_shows(
        self,
        movie_id: str,
        location: NormalizedLocation,
        target_date: Optional[str] = None,
    ) -> List[Show]:
        """
        Fetch showtimes for the movie in the user's location on the target date.

        Args:
            movie_id: Platform-specific movie ID.
            location: Normalized location with coordinates and city.
            target_date: Date string YYYY-MM-DD. Defaults to today.

        Returns:
            List[Show]: List of Show objects with cinema, time, format, price, seat status, URL.
        """
        query_date = target_date or datetime.now().strftime("%Y-%m-%d")
        url = f"{self.API_URL}/movies/{movie_id}/shows"
        params = {
            "date": query_date,
            "lat": location.latitude,
            "lng": location.longitude,
        }

        try:
            data = await http_client.get_json(url, params=params)

            shows: List[Show] = []
            for item in data.get("shows", []):
                cinema_name = item.get("cinema_name")
                cinema_id = item.get("cinema_id")
                show_time = item.get("time")  # e.g. "19:30" or "07:30 PM"
                format_type = item.get("format", "2D")
                language = item.get("language", "English")

                # Derive seat availability and status
                avail = item.get("available_seats")
                total = item.get("total_seats")
                seat_status = SeatStatus.AVAILABLE
                if avail is not None and total is not None and total > 0:
                    pct = (avail / total) * 100
                    if avail == 0:
                        seat_status = SeatStatus.SOLD_OUT
                    elif pct < 15:
                        seat_status = SeatStatus.ALMOST_FULL
                    elif pct < 40:
                        seat_status = SeatStatus.FILLING_FAST

                # Deep link directly to seat selection or booking page
                booking_url = f"{self.BASE_URL}/booking?movie={movie_id}&cinema={cinema_id}&date={query_date}"

                # Generate a reproducible unique ID for diff engine comparison
                show_id = f"{self.platform_name}:{cinema_id}:{query_date}:{show_time}:{format_type}:{language}"

                shows.append(
                    Show(
                        show_id=show_id,
                        platform=self.platform_name,
                        movie_id=movie_id,
                        movie_title=item.get("movie_title", "Movie"),
                        cinema_name=cinema_name,
                        cinema_id=cinema_id,
                        cinema_chain=item.get("chain"),
                        latitude=item.get("latitude"),
                        longitude=item.get("longitude"),
                        date=query_date,
                        time=show_time,
                        format=format_type,
                        language=language,
                        min_price=item.get("min_price"),
                        max_price=item.get("max_price"),
                        currency=item.get("currency", "USD"),
                        available_seats=avail,
                        total_seats=total,
                        seat_status=seat_status,
                        booking_url=booking_url,
                        raw_data=item,
                    )
                )

            return shows

        except Exception as err:
            logger.error(f"Error fetching shows on {self.platform_name}: {err}")
            return []

    async def health_check(self) -> bool:
        """
        Check if the platform endpoints are reachable and responsive.
        """
        try:
            # Simple ping or root check
            await http_client.get_json(f"{self.API_URL}/status")
            return True
        except Exception:
            return False
