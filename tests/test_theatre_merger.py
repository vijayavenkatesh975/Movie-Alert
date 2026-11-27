"""Unit tests for theatre merging, rapidfuzz fuzzy matching, and deduplication."""

import pytest
from ticketnotify.adapters.base import Cinema
from ticketnotify.location.theatre_merger import (
    merge_theatres,
    is_same_theatre,
    MergedCinema,
)


def test_merge_theatres_duplicate_across_platforms():
    # BMS cinema in Koramangala
    bms_cinema = Cinema(
        cinema_id="BMS_PVR01",
        platform="bms",
        name="PVR IMAX: Forum Mall, Koramangala",
        city="Bengaluru",
        latitude=12.9352,
        longitude=77.6111,
        chain="PVR",
        distance_km=4.2,
    )

    # PVR INOX cinema at the same mall with slightly different name
    pvr_cinema = Cinema(
        cinema_id="PVR_102",
        platform="pvrinox",
        name="PVR Forum Mall Koramangala Bengaluru",
        city="Bengaluru",
        latitude=12.9353,
        longitude=77.6112,
        chain="PVR",
        distance_km=4.2,
    )

    # Separate cinema in Magrath road (4 km away)
    inox_cinema = Cinema(
        cinema_id="BMS_INOX02",
        platform="bms",
        name="INOX: Garuda Mall, Magrath Road",
        city="Bengaluru",
        latitude=12.9705,
        longitude=77.6097,
        chain="INOX",
        distance_km=2.1,
    )

    merged = merge_theatres([bms_cinema, pvr_cinema, inox_cinema], max_distance_meters=300.0)

    # Should merge BMS and PVR Forum into 1, leaving 2 canonical cinemas
    assert len(merged) == 2

    # Find the merged PVR Forum
    forum = next(m for m in merged if "Forum" in m.name)
    assert forum.platform_cinema_ids.get("bms") == "BMS_PVR01"
    assert forum.platform_cinema_ids.get("pvrinox") == "PVR_102"
    assert forum.chain == "PVR"

    # Garuda Mall remains distinct
    garuda = next(m for m in merged if "Garuda" in m.name)
    assert garuda.platform_cinema_ids.get("bms") == "BMS_INOX02"
    assert "pvrinox" not in garuda.platform_cinema_ids


def test_theatres_sorted_by_distance():
    c_far = Cinema(
        cinema_id="FAR1",
        platform="bms",
        name="Far Cinema",
        city="Bengaluru",
        distance_km=15.0,
    )
    c_near = Cinema(
        cinema_id="NEAR1",
        platform="bms",
        name="Near Cinema",
        city="Bengaluru",
        distance_km=1.5,
    )
    c_mid = Cinema(
        cinema_id="MID1",
        platform="bms",
        name="Mid Cinema",
        city="Bengaluru",
        distance_km=6.0,
    )

    merged = merge_theatres([c_far, c_near, c_mid])
    assert [m.name for m in merged] == ["Near Cinema", "Mid Cinema", "Far Cinema"]


@pytest.mark.asyncio
async def test_live_theatre_discovery_caching_and_unmapped(monkeypatch):
    """Verifies that theatres are queried live, unmapped cinemas are logged and kept,
    and 12-hour caching / force_refresh works properly.
    """
    from unittest.mock import AsyncMock
    from ticketnotify.location.models import NormalizedLocation
    from ticketnotify.location.theatre_merger import get_theatres_for_location
    from ticketnotify.database.session import init_db
    from ticketnotify.adapters.registry import registry

    await init_db()

    norm_loc = NormalizedLocation(
        raw_query="Madurai",
        city="Madurai",
        country="India",
        country_code="in",
        latitude=9.9252,
        longitude=78.1198,
        display_name="Madurai, India",
    )

    unmapped_cinema = Cinema(
        cinema_id="LIVE_MDU_01",
        platform="ticketnew",
        name="Vetri Cinemas - Villapuram",
        city="Madurai",
        latitude=9.9123,
        longitude=78.1345,
        address="Villapuram Main Rd, Madurai",
    )

    mock_adapter = AsyncMock()
    mock_adapter.is_location_supported = lambda loc: True
    mock_adapter.get_cinemas.return_value = [unmapped_cinema]

    monkeypatch.setattr(registry, "get_adapter", lambda p: mock_adapter if p == "ticketnew" else None)

    # 1. First fetch: live discovery
    results = await get_theatres_for_location(norm_loc, platforms=["ticketnew"], force_refresh=True)
    assert any("Vetri Cinemas" in t.name for t in results)
    vetri = next(t for t in results if "Vetri Cinemas" in t.name)
    assert vetri.locality == "Villapuram"

    # 2. Second fetch without force_refresh: should hit cache
    mock_adapter.get_cinemas.reset_mock()
    cached_results = await get_theatres_for_location(norm_loc, platforms=["ticketnew"], force_refresh=False)
    assert any("Vetri Cinemas" in t.name for t in cached_results)
    assert mock_adapter.get_cinemas.call_count == 0

    # 3. Third fetch with force_refresh: calls adapter again
    await get_theatres_for_location(norm_loc, platforms=["ticketnew"], force_refresh=True)
    assert mock_adapter.get_cinemas.call_count == 1
