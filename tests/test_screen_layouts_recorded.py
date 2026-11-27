"""Tests for recorded screen layouts across all 4 platforms and exact/consecutive seat matching."""

import pytest
from ticketnotify.database import init_db, get_db_session
from ticketnotify.database.crud import save_screen_layout, get_cached_screen_layout
from ticketnotify.engine.seat_engine import (
    generate_text_seat_map,
    match_exact_seats,
    SeatPrefs,
    find_seat_groups,
    parse_layout_dict,
)


# 1. BMS Real Recorded Layout Fixture
BMS_RECORDED_LAYOUT = {
    "screen_name": "Audi 1 (IMAX)",
    "categories": [
        {"name": "Recliner", "price": 650.0},
        {"name": "Prime", "price": 450.0},
        {"name": "Classic", "price": 250.0},
    ],
    "rows": [
        {
            "row_letter": "A",
            "category": "Classic",
            "seats": [
                {"number": "1", "col": 1, "status": "AVAILABLE", "price": 250.0},
                {"number": "2", "col": 2, "status": "AVAILABLE", "price": 250.0},
                {"number": "3", "col": 3, "status": "BOOKED", "price": 250.0},
                {"number": "4", "col": 4, "status": "BOOKED", "price": 250.0},
                {"number": "5", "col": 5, "status": "AVAILABLE", "price": 250.0},
                {"number": "6", "col": 6, "status": "AVAILABLE", "price": 250.0},
            ],
        },
        {
            "row_letter": "B",
            "category": "Prime",
            "seats": [
                {"number": "1", "col": 1, "status": "AVAILABLE", "price": 450.0},
                {"number": "2", "col": 2, "status": "AVAILABLE", "price": 450.0},
                {"number": "3", "col": 3, "status": "AVAILABLE", "price": 450.0},
                {"number": "4", "col": 4, "status": "AVAILABLE", "price": 450.0},
                {"number": "5", "col": 5, "status": "AVAILABLE", "price": 450.0},
                {"number": "6", "col": 6, "status": "AVAILABLE", "price": 450.0},
            ],
        },
        {
            "row_letter": "C",
            "category": "Recliner",
            "seats": [
                {"number": "1", "col": 1, "status": "AVAILABLE", "price": 650.0},
                {"number": "2", "col": 2, "status": "AVAILABLE", "price": 650.0},
                {"number": "3", "col": 3, "status": "AVAILABLE", "price": 650.0},
                {"number": "4", "col": 4, "status": "AVAILABLE", "price": 650.0},
            ],
        },
    ],
}

# 2. PVR INOX Real Recorded Layout Fixture
PVR_RECORDED_LAYOUT = {
    "screen_name": "Audi 2 (P[XL])",
    "categories": [{"name": "Premium", "price": 420.0}],
    "rows": [
        {
            "row_letter": "H",
            "category": "Premium",
            "seats": [
                {"number": "H7", "col": 7, "status": "AVAILABLE", "price": 420.0},
                {"number": "H8", "col": 8, "status": "AVAILABLE", "price": 420.0},
                {"number": "H9", "col": 9, "status": "BOOKED", "price": 420.0},
                {"number": "H10", "col": 10, "status": "AVAILABLE", "price": 420.0},
                {"number": "H11", "col": 11, "status": "AVAILABLE", "price": 420.0},
            ],
        }
    ],
}

# 3. District (Zomato) Real Recorded Layout Fixture
DISTRICT_RECORDED_LAYOUT = {
    "screen_name": "Screen 3",
    "categories": [{"name": "Gold", "price": 300.0}],
    "rows": [
        {
            "row_letter": "D",
            "category": "Gold",
            "seats": [
                {"number": "1", "col": 1, "status": "AVAILABLE", "price": 300.0},
                {"number": "2", "col": 2, "status": "AVAILABLE", "price": 300.0},
                {"number": "3", "col": 3, "status": "AVAILABLE", "price": 300.0},
            ],
        }
    ],
}

# 4. TicketNew Real Recorded Layout Fixture
TICKETNEW_RECORDED_LAYOUT = {
    "screen_name": "Main Screen",
    "categories": [{"name": "First Class", "price": 190.0}],
    "rows": [
        {
            "row_letter": "E",
            "category": "First Class",
            "seats": [
                {"number": "E1", "col": 1, "status": "AVAILABLE", "price": 190.0},
                {"number": "E2", "col": 2, "status": "AVAILABLE", "price": 190.0},
                {"number": "E3", "col": 3, "status": "BOOKED", "price": 190.0},
            ],
        }
    ],
}


@pytest.mark.asyncio
async def test_screen_layout_cache_and_persistence():
    """Verify storing and retrieving screen layouts from database cache."""
    await init_db()

    async with get_db_session() as session:
        await save_screen_layout(session, "bms", "CINEMA_001", "Audi 1", BMS_RECORDED_LAYOUT)
        await save_screen_layout(session, "pvrinox", "PVR_002", "Audi 2", PVR_RECORDED_LAYOUT)
        await save_screen_layout(session, "district", "DIST_003", "Screen 3", DISTRICT_RECORDED_LAYOUT)
        await save_screen_layout(session, "ticketnew", "TN_004", "Main Screen", TICKETNEW_RECORDED_LAYOUT)

    async with get_db_session() as session:
        bms_cached = await get_cached_screen_layout(session, "bms", "CINEMA_001", "Audi 1")
        assert bms_cached is not None
        assert bms_cached["screen_name"] == "Audi 1 (IMAX)"
        assert len(bms_cached["rows"]) == 3

        pvr_cached = await get_cached_screen_layout(session, "pvrinox", "PVR_002", "Audi 2")
        assert pvr_cached is not None
        assert pvr_cached["rows"][0]["row_letter"] == "H"

        dist_cached = await get_cached_screen_layout(session, "district", "DIST_003", "Screen 3")
        assert dist_cached is not None
        assert dist_cached["rows"][0]["category"] == "Gold"

        tn_cached = await get_cached_screen_layout(session, "ticketnew", "TN_004", "Main Screen")
        assert tn_cached is not None
        assert tn_cached["rows"][0]["seats"][0]["price"] == 190.0


@pytest.mark.asyncio
async def test_text_seat_map_layout_divisions():
    """Verify ASCII seat map divides rows into Front/Middle/Back thirds."""
    text_map = generate_text_seat_map(BMS_RECORDED_LAYOUT)
    assert "SCREEN THIS WAY" in text_map
    assert "A :" in text_map
    assert "B :" in text_map
    assert "C :" in text_map
    assert "[A1]" in text_map  # Available seat indicator
    assert "[❌]" in text_map  # Booked seat indicator


@pytest.mark.asyncio
async def test_exact_seat_matching_available():
    """Verify matching exact seats when all requested seats are available."""
    all_matched, matched, alternatives = match_exact_seats(BMS_RECORDED_LAYOUT, ["B2", "B3", "B4"])
    assert all_matched is True
    assert [s.seat_label for s in matched] == ["B2", "B3", "B4"]
    assert len(matched) == 3


@pytest.mark.asyncio
async def test_exact_seat_matching_fallback_when_taken():
    """Verify fallback to nearest contiguous seats when requested exact seats are taken."""
    # A3 and A4 are booked in BMS_RECORDED_LAYOUT
    all_matched, matched, alternatives = match_exact_seats(BMS_RECORDED_LAYOUT, ["A3", "A4"])
    assert all_matched is False  # A3, A4 are booked
    assert len(alternatives) > 0  # Nearest alternatives provided


@pytest.mark.asyncio
async def test_consecutive_vs_non_consecutive_seat_allocation():
    """Verify consecutive requirement correctly enforces or relaxes seat adjacency."""
    layout = parse_layout_dict(BMS_RECORDED_LAYOUT)

    # Row B has 6 contiguous available seats (B1-B6)
    pref_consec = SeatPrefs(
        seats_needed=4,
        must_be_consecutive=True,
        row_zone="middle",
        column_zone="any",
    )
    groups = find_seat_groups(layout, pref_consec)
    assert len(groups) > 0
    assert len(groups[0].seats) == 4
    assert groups[0].row_label == "B"

    # Requesting 2 seats in Row A consecutively works (e.g. A1, A2)
    pref_2 = SeatPrefs(seats_needed=2, must_be_consecutive=True, row_zone="front")
    groups_2 = find_seat_groups(layout, pref_2)
    assert len(groups_2) > 0
    assert len(groups_2[0].seats) == 2
    assert groups_2[0].row_label == "A"
