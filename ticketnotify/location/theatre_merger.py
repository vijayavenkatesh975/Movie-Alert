"""Theatre discovery, duplicate merging across platforms using rapidfuzz + Haversine."""

import asyncio
import hashlib
import logging
from typing import List, Dict, Optional, Any, Set
from pydantic import BaseModel, Field
import rapidfuzz

from ticketnotify.adapters.base import Cinema
from ticketnotify.location.distance import haversine_distance_km
from ticketnotify.location.models import NormalizedLocation
from ticketnotify.adapters.registry import registry

logger = logging.getLogger(__name__)

COMMON_CHAINS = [
    "PVR",
    "INOX",
    "Cinepolis",
    "Miraj",
    "MovieMax",
    "SPI",
    "Wave",
    "Carnival",
    "Mukta A2",
    "Rajhans",
    "Cinepolis VIP",
]


class MergedCinema(BaseModel):
    canonical_id: str
    name: str
    city: str
    chain: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    distance_km: Optional[float] = None
    address: Optional[str] = None
    # Mapping platform -> platform-specific cinema_id
    platform_cinema_ids: Dict[str, str] = Field(default_factory=dict)

    @property
    def display_label(self) -> str:
        """Formatted string for inline buttons: e.g. 'PVR Forum Mall - 2.4 km'"""
        dist_str = f" - {self.distance_km:.1f} km" if self.distance_km is not None else ""
        return f"{self.name}{dist_str}"


def extract_chain_from_name(name: str) -> Optional[str]:
    name_upper = name.upper()
    for chain in COMMON_CHAINS:
        if chain.upper() in name_upper:
            return chain
    return None


def generate_canonical_id(name: str, city: str, lat: Optional[float], lng: Optional[float]) -> str:
    """Generates a stable deterministic canonical ID for a theatre."""
    if lat is not None and lng is not None:
        # Round coords to 3 decimals (~110 meters) for spatial bucket grouping
        key = f"{city.lower()}:{round(lat, 3)}:{round(lng, 3)}:{name.lower()[:10]}"
    else:
        key = f"{city.lower()}:{name.lower()}"
    return "cin_" + hashlib.md5(key.encode("utf-8")).hexdigest()[:10]


def is_same_theatre(
    c1: Cinema,
    c2: MergedCinema,
    max_distance_meters: float = 300.0,
    name_similarity_threshold: float = 75.0,
) -> bool:
    """
    Checks if a Cinema matches a MergedCinema using Haversine distance < 300m
    and fuzzy name matching with rapidfuzz.
    """
    # 1. Coordinate-based check if both have coordinates
    if (
        c1.latitude is not None
        and c1.longitude is not None
        and c2.latitude is not None
        and c2.longitude is not None
    ):
        dist_km = haversine_distance_km(c1.latitude, c1.longitude, c2.latitude, c2.longitude)
        dist_meters = dist_km * 1000.0

        if dist_meters <= max_distance_meters:
            # Under 300 meters: check name similarity
            ratio = rapidfuzz.fuzz.token_set_ratio(c1.name.lower(), c2.name.lower())
            if ratio >= name_similarity_threshold:
                return True
            # Also match if both belong to the same chain and are < 300m
            ch1 = c1.chain or extract_chain_from_name(c1.name)
            ch2 = c2.chain or extract_chain_from_name(c2.name)
            if ch1 and ch2 and ch1.lower() == ch2.lower() and ratio >= 55.0:
                return True

    # 2. Name-based check when coordinates are missing or approximate
    ratio = rapidfuzz.fuzz.token_set_ratio(c1.name.lower(), c2.name.lower())
    if ratio >= 88.0 and c1.city.lower() == c2.city.lower():
        return True

    return False


def merge_theatres(
    cinemas: List[Cinema],
    max_distance_meters: float = 300.0,
    name_similarity_threshold: float = 75.0,
) -> List[MergedCinema]:
    """
    Merges duplicate cinema representations across multiple booking platforms
    into a canonical list of MergedCinema objects.
    """
    merged: List[MergedCinema] = []

    for c in cinemas:
        matched: Optional[MergedCinema] = None
        for m in merged:
            if is_same_theatre(c, m, max_distance_meters, name_similarity_threshold):
                matched = m
                break

        if matched:
            # Map this platform's cinema_id
            matched.platform_cinema_ids[c.platform] = c.cinema_id
            # Merge missing metadata
            if not matched.chain and c.chain:
                matched.chain = c.chain
            if matched.latitude is None and c.latitude is not None:
                matched.latitude = c.latitude
                matched.longitude = c.longitude
            if matched.distance_km is None and c.distance_km is not None:
                matched.distance_km = c.distance_km
            elif c.distance_km is not None and matched.distance_km is not None:
                matched.distance_km = min(matched.distance_km, c.distance_km)
            if not matched.address and c.address:
                matched.address = c.address
        else:
            chain = c.chain or extract_chain_from_name(c.name)
            cid = generate_canonical_id(c.name, c.city, c.latitude, c.longitude)
            new_merged = MergedCinema(
                canonical_id=cid,
                name=c.name,
                city=c.city,
                chain=chain,
                latitude=c.latitude,
                longitude=c.longitude,
                distance_km=c.distance_km,
                address=c.address,
                platform_cinema_ids={c.platform: c.cinema_id},
            )
            merged.append(new_merged)

    # Sort ascending by distance (unknown distance at the end)
    merged.sort(key=lambda x: (x.distance_km is None, x.distance_km or 999.0, x.name))
    return merged


async def get_theatres_for_location(
    location: NormalizedLocation,
    platforms: Optional[List[str]] = None,
    radius_km: float = 10.0,
) -> List[MergedCinema]:
    """
    Fetches cinemas across all active platforms within radius_km and returns
    a deduplicated list of canonical theatres sorted by distance.
    """
    active_platforms = platforms or location.supported_platforms or ["bms", "ticketnew", "district", "pvrinox"]
    tasks = []

    for p in active_platforms:
        adapter = registry.get_adapter(p)
        if adapter and adapter.is_location_supported(location):
            tasks.append(adapter.get_cinemas(location, radius_km=radius_km))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_cinemas: List[Cinema] = []
    for r in results:
        if isinstance(r, list):
            all_cinemas.extend(r)
        elif isinstance(r, Exception):
            logger.warning(f"Error fetching cinemas from platform: {r}")

    return merge_theatres(all_cinemas, max_distance_meters=300.0)
