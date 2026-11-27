"""Common interface and data models for all platform adapters."""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

from ticketnotify.location.models import NormalizedLocation


class SeatStatus(str, Enum):
    AVAILABLE = "available"
    FILLING_FAST = "filling_fast"
    ALMOST_FULL = "almost_full"
    SOLD_OUT = "sold_out"


class FetchStatus(str, Enum):
    OK = "OK"
    BLOCKED = "BLOCKED"          # 403, Cloudflare/WAF, CAPTCHA
    UNAVAILABLE = "UNAVAILABLE"  # 5xx, Network down, DNS fail, Timeout
    PARSE_ERROR = "PARSE_ERROR"  # Malformed JSON, schema breakdown


class MovieMatch(BaseModel):
    movie_id: str
    platform: str
    title: str
    languages: List[str] = Field(default_factory=list)
    formats: List[str] = Field(default_factory=list)
    poster_url: Optional[str] = None
    release_date: Optional[str] = None
    genres: List[str] = Field(default_factory=list)
    rating: Optional[str] = None
    url: Optional[str] = None
    extra_metadata: Dict[str, Any] = Field(default_factory=dict)


class Show(BaseModel):
    show_id: str  # Unique hash/key identifying cinema + time + format
    platform: str
    movie_id: str
    movie_title: str
    cinema_name: str
    cinema_id: str
    cinema_chain: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    date: str  # YYYY-MM-DD
    time: str  # HH:MM or 12-hour format e.g. "07:30 PM"
    format: str = "2D"  # 2D, 3D, IMAX 3D, 4DX, Dolby Atmos, etc.
    language: str = "Unknown"
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    currency: str = "INR"
    available_seats: Optional[int] = None
    total_seats: Optional[int] = None
    seat_status: SeatStatus = SeatStatus.AVAILABLE
    booking_url: str
    raw_data: Dict[str, Any] = Field(default_factory=dict)

    @property
    def price_display(self) -> str:
        if self.min_price is not None and self.max_price is not None:
            if self.min_price == self.max_price:
                return f"{self.currency} {int(self.min_price)}"
            return f"{self.currency} {int(self.min_price)} - {int(self.max_price)}"
        if self.min_price is not None:
            return f"From {self.currency} {int(self.min_price)}"
        return "Price N/A"

    @property
    def seat_status_display(self) -> str:
        status_emojis = {
            SeatStatus.AVAILABLE: "🟢 Available",
            SeatStatus.FILLING_FAST: "🟡 Filling Fast",
            SeatStatus.ALMOST_FULL: "🟠 Almost Full",
            SeatStatus.SOLD_OUT: "🔴 Sold Out",
        }
        text = status_emojis.get(self.seat_status, "🟢 Available")
        if self.available_seats is not None:
            text += f" ({self.available_seats} seats left)"
        return text


class Cinema(BaseModel):
    cinema_id: str
    platform: str
    name: str
    city: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    chain: Optional[str] = None  # PVR, INOX, Cinepolis, MovieMax, etc.
    locality: Optional[str] = None
    mall: Optional[str] = None
    address: Optional[str] = None
    distance_km: Optional[float] = None
    extra_metadata: Dict[str, Any] = Field(default_factory=dict)


class FetchResult(BaseModel):
    status: FetchStatus
    shows: List[Show] = Field(default_factory=list)
    error_message: Optional[str] = None
    http_status: Optional[int] = None
    latency_ms: float = 0.0

    @classmethod
    def ok(cls, shows: List[Show], latency_ms: float = 0.0) -> "FetchResult":
        return cls(status=FetchStatus.OK, shows=shows, latency_ms=latency_ms)

    @classmethod
    def blocked(cls, message: str, http_status: Optional[int] = 403, latency_ms: float = 0.0) -> "FetchResult":
        return cls(status=FetchStatus.BLOCKED, error_message=message, http_status=http_status, latency_ms=latency_ms)

    @classmethod
    def unavailable(cls, message: str, http_status: Optional[int] = None, latency_ms: float = 0.0) -> "FetchResult":
        return cls(status=FetchStatus.UNAVAILABLE, error_message=message, http_status=http_status, latency_ms=latency_ms)

    @classmethod
    def parse_error(cls, message: str, latency_ms: float = 0.0) -> "FetchResult":
        return cls(status=FetchStatus.PARSE_ERROR, error_message=message, latency_ms=latency_ms)

    @property
    def is_success(self) -> bool:
        return self.status == FetchStatus.OK

    def __iter__(self):
        """Allows iterating directly over shows for compatibility if needed."""
        return iter(self.shows)

    def __len__(self):
        return len(self.shows)


def classify_fetch_error(e: Exception, latency_ms: float = 0.0) -> FetchResult:
    """Classifies an exception into Blocked, Unavailable, or ParseError."""
    import httpx
    msg = str(e)
    if isinstance(e, httpx.HTTPStatusError):
        code = e.response.status_code
        if code in (403, 429):
            return FetchResult.blocked(f"HTTP {code} Blocked/Rate limited: {msg}", http_status=code, latency_ms=latency_ms)
        elif code >= 500:
            return FetchResult.unavailable(f"HTTP {code} Server error: {msg}", http_status=code, latency_ms=latency_ms)
        else:
            return FetchResult.unavailable(f"HTTP {code} Error: {msg}", http_status=code, latency_ms=latency_ms)
    elif isinstance(e, (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.NetworkError)):
        return FetchResult.unavailable(f"Network error / unreachable: {msg}", latency_ms=latency_ms)
    elif "getaddrinfo" in msg or "11001" in msg or "ConnectionRefused" in msg:
        return FetchResult.unavailable(f"DNS/Network resolution failure: {msg}", latency_ms=latency_ms)
    elif isinstance(e, (ValueError, KeyError, TypeError)) or "JSON" in msg or "Expecting value" in msg:
        return FetchResult.parse_error(f"Malformed JSON or schema break: {msg}", latency_ms=latency_ms)
    elif "403" in msg or "Forbidden" in msg or "Cloudflare" in msg:
        return FetchResult.blocked(f"Blocked: {msg}", http_status=403, latency_ms=latency_ms)
    return FetchResult.unavailable(f"Unexpected error: {msg}", latency_ms=latency_ms)


class PlatformAdapter(ABC):
    """Abstract Base Class for all cinema booking platform adapters."""

    platform_name: str
    platform_label: str
    supported_countries: List[str]

    def is_location_supported(self, location: NormalizedLocation) -> bool:
        """Check if this platform operates in the location's country."""
        country_code = (location.country_code or "").lower()
        return country_code in [c.lower() for c in self.supported_countries]

    @abstractmethod
    async def search_movie(
        self,
        title: str,
        location: NormalizedLocation,
    ) -> List[MovieMatch]:
        """
        Search for movies matching title in the given location.
        Returns a list of MovieMatch objects.
        """
        pass

    @abstractmethod
    async def get_shows(
        self,
        movie_id: str,
        location: NormalizedLocation,
        target_date: Optional[str] = None,
    ) -> FetchResult:
        """
        Fetch all available shows for movie_id in the given location and date.
        Returns a typed FetchResult (Ok, Blocked, Unavailable, ParseError).
        """
        pass

    async def get_cinemas(
        self,
        location: NormalizedLocation,
        radius_km: float = 10.0,
    ) -> List[Cinema]:
        """
        Fetch cinemas operating in this location within the given radius.
        """
        return []

    async def get_seat_layout(
        self,
        show_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch raw seat layout dictionary for the given show ID.
        """
        return None

    @abstractmethod
    async def health_check(self) -> bool:
        """
        Verifies endpoint availability and returns True if healthy.
        """
        pass
