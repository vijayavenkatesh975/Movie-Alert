"""Theatre discovery, duplicate merging across platforms using rapidfuzz + Haversine.

Supports complete city-wide theatre selection (no radius restriction), rich locality/mall metadata,
and robust cross-platform canonical ID deduplication.
"""

import asyncio
import hashlib
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any, Set
from pydantic import BaseModel, Field
import rapidfuzz

from ticketnotify.adapters.base import Cinema
from ticketnotify.location.distance import haversine_distance_km
from ticketnotify.location.models import NormalizedLocation
from ticketnotify.adapters.registry import registry
from ticketnotify.location.theatre_directory import get_theatres_by_city

logger = logging.getLogger(__name__)

COMMON_CHAINS = [
    "PVR",
    "INOX",
    "Cinepolis",
    "AGS",
    "Rohini",
    "Mayajaal",
    "Devi",
    "Sangam",
    "Rakki",
    "EVP",
    "Miraj",
    "MovieMax",
    "SPI",
    "Wave",
    "Carnival",
    "Mukta A2",
    "Rajhans",
]


class MergedCinema(BaseModel):
    canonical_id: str
    name: str
    city: str
    chain: Optional[str] = None
    locality: Optional[str] = None
    mall: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    distance_km: Optional[float] = None
    address: Optional[str] = None
    # Mapping platform -> platform-specific cinema_id
    platform_cinema_ids: Dict[str, str] = Field(default_factory=dict)

    @property
    def display_platforms(self) -> List[str]:
        plat_map = {
            "bms": "BMS",
            "pvrinox": "PVR",
            "ticketnew": "TN",
            "district": "DIST",
        }
        return [plat_map.get(p.lower(), p.upper()) for p in self.platform_cinema_ids.keys()]

    @property
    def display_label(self) -> str:
        """Formatted string for inline buttons: e.g. 'PVR Palazzo – Vadapalani (2.4 km)'"""
        dist_str = f" ({self.distance_km:.1f} km)" if self.distance_km is not None else ""
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
        key = f"{city.lower()}:{round(lat, 3)}:{round(lng, 3)}:{name.lower()[:12]}"
    else:
        key = f"{city.lower()}:{name.lower()[:15]}"
    return "cin_" + hashlib.md5(key.encode("utf-8")).hexdigest()[:10]


def is_same_theatre(
    c1: Cinema,
    c2: MergedCinema,
    max_distance_meters: float = 300.0,
    name_similarity_threshold: float = 75.0,
) -> bool:
    """Checks if a Cinema matches a MergedCinema using Haversine distance < 300m
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
            ratio = rapidfuzz.fuzz.token_set_ratio(c1.name.lower(), c2.name.lower())
            if ratio >= name_similarity_threshold:
                return True
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
    """Merges duplicate cinema representations across multiple booking platforms
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
            matched.platform_cinema_ids[c.platform] = c.cinema_id
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
            if not matched.locality and c.locality:
                matched.locality = c.locality
            if not matched.mall and c.mall:
                matched.mall = c.mall
        else:
            chain = c.chain or extract_chain_from_name(c.name)
            cid = generate_canonical_id(c.name, c.city, c.latitude, c.longitude)
            new_merged = MergedCinema(
                canonical_id=cid,
                name=c.name,
                city=c.city,
                chain=chain,
                locality=c.locality,
                mall=c.mall,
                latitude=c.latitude,
                longitude=c.longitude,
                distance_km=c.distance_km,
                address=c.address,
                platform_cinema_ids={c.platform: c.cinema_id},
            )
            merged.append(new_merged)

    # Sort ascending by distance when available, otherwise alphabetical
    merged.sort(key=lambda x: (x.distance_km is None, x.distance_km or 999.0, x.name))
    return merged


async def get_theatres_for_location(
    location: NormalizedLocation,
    platforms: Optional[List[str]] = None,
    radius_km: Optional[float] = None,
    force_refresh: bool = False,
) -> List[MergedCinema]:
    """Fetches all cinemas operating in the user's city across all platforms.

    Queries platform endpoints live, caches results in DB/Redis with 12h TTL,
    uses master directory as canonical metadata merge source, logs unmapped cinemas,
    and supports force refresh.
    """
    city_name = location.city or "Chennai"

    # 1. Cache lookup if not force_refresh
    if not force_refresh:
        # Check Redis cache first (12h TTL)
        try:
            from ticketnotify.cache.redis import cache_get
            raw_cached = await cache_get(f"theatres:{city_name.lower()}")
            if raw_cached:
                items = json.loads(raw_cached)
                return [MergedCinema(**item) for item in items]
        except Exception as e:
            logger.debug(f"Redis cache lookup error: {e}")

        try:
            from ticketnotify.database.session import get_db_session
            from ticketnotify.database.models import CachedTheatres
            from sqlalchemy import select

            async with get_db_session() as session:
                cached_row = await session.scalar(
                    select(CachedTheatres).where(CachedTheatres.city == city_name)
                )
                if cached_row and (datetime.utcnow() - cached_row.fetched_at).total_seconds() < 43200:
                    cached_theatres = [MergedCinema(**item) for item in cached_row.theatres_json]
                    if cached_theatres:
                        return cached_theatres
        except Exception as e:
            logger.debug(f"Cache lookup failed for {city_name}: {e}")
    else:
        try:
            from ticketnotify.cache.redis import cache_delete
            await cache_delete(f"theatres:{city_name.lower()}")
        except Exception as e:
            logger.debug(f"Redis cache delete error: {e}")

    all_cinemas: List[Cinema] = []

    # 2. Query live platform adapters
    active_platforms = platforms or location.supported_platforms or ["bms", "ticketnew", "district", "pvrinox"]
    tasks = []
    effective_radius = radius_km if radius_km is not None else 50.0

    for p in active_platforms:
        adapter = registry.get_adapter(p)
        if adapter and adapter.is_location_supported(location):
            tasks.append(adapter.get_cinemas(location, radius_km=effective_radius))

    live_cinemas: List[Cinema] = []
    if tasks:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, list):
                live_cinemas.extend(r)
            elif isinstance(r, Exception):
                logger.debug(f"Platform cinema query exception: {r}")

    directory_theatres = get_theatres_by_city(city_name)
    dir_lookup = {dt["name"].lower(): dt for dt in directory_theatres}

    # Process live cinemas: audit against master directory
    for c in live_cinemas:
        matched = False
        for d_name, d_info in dir_lookup.items():
            if rapidfuzz.fuzz.token_set_ratio(c.name.lower(), d_name) >= 80:
                matched = True
                if not getattr(c, "locality", None) and d_info.get("locality"):
                    c.locality = d_info["locality"]
                if not getattr(c, "chain", None) and d_info.get("chain"):
                    c.chain = d_info["chain"]
                if not c.latitude and d_info.get("latitude"):
                    c.latitude = d_info["latitude"]
                if not c.longitude and d_info.get("longitude"):
                    c.longitude = d_info["longitude"]
                break
        if not matched:
            logger.warning(
                f"UNMAPPED CINEMA DISCOVERED: '{c.name}' in {c.city} [{c.platform}:{c.cinema_id}] - logged for review"
            )
            # Infer locality if missing
            if not getattr(c, "locality", None):
                parts = c.name.replace("–", "-").split("-")
                if len(parts) > 1:
                    c.locality = parts[-1].strip()

        all_cinemas.append(c)

    # 3. Seed canonical directory records (as metadata/canonical merge source)
    for dt in directory_theatres:
        lat = dt.get("latitude")
        lng = dt.get("longitude")
        dist = None
        if lat and lng and location.latitude and location.longitude:
            dist = round(haversine_distance_km(location.latitude, location.longitude, lat, lng), 2)
            if radius_km is not None and dist > radius_km:
                continue

        p_cids = dt.get("platform_cinema_ids", {})
        for plat, cid in p_cids.items():
            all_cinemas.append(
                Cinema(
                    cinema_id=cid,
                    platform=plat,
                    name=dt["name"],
                    city=city_name,
                    chain=dt.get("chain"),
                    latitude=lat,
                    longitude=lng,
                    address=dt.get("address"),
                    distance_km=dist,
                )
            )

    # 4. Deduplicate across platforms
    merged = merge_theatres(all_cinemas, max_distance_meters=300.0)

    # Populate locality and mall from directory records if matched
    for m in merged:
        for d_name, d_info in dir_lookup.items():
            if rapidfuzz.fuzz.token_set_ratio(m.name.lower(), d_name) >= 80:
                if not m.locality and d_info.get("locality"):
                    m.locality = d_info["locality"]
                if not m.mall and d_info.get("mall"):
                    m.mall = d_info["mall"]
                break

    # 5. Store into CachedTheatres & Redis (12h TTL)
    try:
        from ticketnotify.cache.redis import cache_set
        theatres_payload = [m.model_dump() for m in merged]
        await cache_set(f"theatres:{city_name.lower()}", json.dumps(theatres_payload), ttl_seconds=12 * 3600)
    except Exception as e:
        logger.debug(f"Saving to Redis cache failed: {e}")

    try:
        from ticketnotify.database.session import get_db_session
        from ticketnotify.database.models import CachedTheatres
        from sqlalchemy import select

        async with get_db_session() as session:
            existing_row = await session.scalar(
                select(CachedTheatres).where(CachedTheatres.city == city_name)
            )
            theatres_payload = [m.model_dump() for m in merged]
            if existing_row:
                existing_row.theatres_json = theatres_payload
                existing_row.fetched_at = datetime.utcnow()
            else:
                session.add(
                    CachedTheatres(
                        city=city_name,
                        theatres_json=theatres_payload,
                        fetched_at=datetime.utcnow(),
                    )
                )
            await session.commit()
    except Exception as e:
        logger.debug(f"Saving to CachedTheatres failed: {e}")

    return merged


def get_unique_localities(theatres: List[MergedCinema]) -> List[str]:
    """Returns sorted unique localities extracted from theatre records."""
    localities = set()
    for t in theatres:
        if t.locality:
            localities.add(t.locality)
        elif "–" in t.name or "-" in t.name:
            sep = "–" if "–" in t.name else "-"
            parts = t.name.split(sep)
            if len(parts) > 1:
                loc = parts[1].strip()
                if "(" in loc:
                    loc = loc.split("(")[0].strip()
                if len(loc) >= 3:
                    localities.add(loc)
    return sorted(list(localities))


def get_unique_chains(theatres: List[MergedCinema]) -> List[str]:
    """Returns sorted unique chains present in the theatre list."""
    chains = set()
    for t in theatres:
        ch = t.chain or extract_chain_from_name(t.name)
        if ch:
            chains.add(ch)
    return sorted(list(chains))


def filter_and_sort_theatres(
    theatres: List[MergedCinema],
    locality: Optional[str] = None,
    chain: Optional[str] = None,
    query: Optional[str] = None,
    sort_by: str = "alpha",  # "alpha" | "distance"
) -> List[MergedCinema]:
    """Filters and sorts theatres by locality, chain, search term, and sort mode."""
    res = list(theatres)

    if locality and locality.lower() != "all":
        loc_low = locality.lower()
        res = [t for t in res if (t.locality and loc_low in t.locality.lower()) or loc_low in t.name.lower()]

    if chain and chain.lower() != "all":
        ch_low = chain.lower()
        res = [t for t in res if (t.chain and ch_low == t.chain.lower()) or ch_low in t.name.lower()]

    if query and query.strip():
        q = query.lower().strip()
        res = [
            t for t in res
            if q in t.name.lower() or (t.mall and q in t.mall.lower()) or (t.locality and q in t.locality.lower())
        ]

    if sort_by == "distance":
        res.sort(key=lambda x: (x.distance_km is None, x.distance_km or 999.0, x.name))
    else:
        res.sort(key=lambda x: x.name.lower())

    return res
