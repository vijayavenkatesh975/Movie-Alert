"""Location data models."""

from typing import Optional, Dict, List
from pydantic import BaseModel, Field


class NormalizedLocation(BaseModel):
    raw_query: str
    city: str
    country: str
    country_code: str  # Lowercase ISO 2-letter code e.g. 'in', 'us', 'gb', 'ae'
    state: Optional[str] = None
    latitude: float
    longitude: float
    display_name: str
    radius_km: float = 20.0
    
    # Platform specific mappings: {"bms": "BANG", "ticketnew": "bangalore", ...}
    platform_codes: Dict[str, Optional[str]] = Field(default_factory=dict)
    
    # Platforms operating vs non-operating in this location
    supported_platforms: List[str] = Field(default_factory=list)
    unsupported_platforms: List[str] = Field(default_factory=list)

    @property
    def label(self) -> str:
        if self.city and self.country:
            return f"{self.city}, {self.country}"
        return self.display_name or self.raw_query
