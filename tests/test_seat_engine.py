"""Unit tests for pure seat preference engine, zone filtering, and scoring."""

import pytest
from ticketnotify.engine.seat_engine import (
    Seat,
    SeatLayout,
    SeatPrefs,
    SeatStatus,
    find_seat_groups,
)


def _build_test_layout(rows: int = 9, cols: int = 10) -> SeatLayout:
    """Builds a synthetic 9-row by 10-col cinema layout."""
    seats = []
    row_labels = ["A", "B", "C", "D", "E", "F", "G", "H", "J"]

    for r in range(rows):
        r_label = row_labels[r % len(row_labels)]
        category = "Recliner" if r >= 7 else ("Premium" if r >= 4 else "Silver")
        price = 600.0 if category == "Recliner" else (350.0 if category == "Premium" else 200.0)

        for c in range(cols):
            # Mark column 3 and 7 as aisle adjacent
            is_aisle = c in (2, 3, 6, 7)
            # Default all available
            seats.append(
                Seat(
                    row_index=r,
                    col_index=c,
                    row_label=r_label,
                    seat_label=f"{r_label}{c + 1}",
                    status=SeatStatus.AVAILABLE,
                    category=category,
                    price=price,
                    is_aisle=is_aisle,
                )
            )

    return SeatLayout(total_rows=rows, total_cols=cols, seats=seats)


def test_consecutive_seats_found():
    layout = _build_test_layout(rows=9, cols=10)
    prefs = SeatPrefs(
        seats_needed=3,
        must_be_consecutive=True,
        row_zone="any",
        column_zone="any",
    )

    groups = find_seat_groups(layout, prefs)
    assert len(groups) > 0
    best = groups[0]
    assert len(best.seats) == 3
    # Check consecutive column indices
    cols = [s.col_index for s in best.seats]
    assert cols[1] == cols[0] + 1
    assert cols[2] == cols[1] + 1


def test_row_zone_filtering():
    layout = _build_test_layout(rows=9, cols=10)

    # 1. Front zone: rows 0, 1, 2 (rows A, B, C)
    front_prefs = SeatPrefs(seats_needed=2, row_zone="front")
    front_groups = find_seat_groups(layout, front_prefs)
    assert all(g.seats[0].row_index < 3 for g in front_groups)

    # 2. Middle zone: rows 3, 4, 5 (rows D, E, F)
    mid_prefs = SeatPrefs(seats_needed=2, row_zone="middle")
    mid_groups = find_seat_groups(layout, mid_prefs)
    assert all(3 <= g.seats[0].row_index < 6 for g in mid_groups)

    # 3. Back zone: rows 6, 7, 8 (rows G, H, J)
    back_prefs = SeatPrefs(seats_needed=2, row_zone="back")
    back_groups = find_seat_groups(layout, back_prefs)
    assert all(g.seats[0].row_index >= 6 for g in back_groups)


def test_column_zone_center():
    layout = _build_test_layout(rows=9, cols=10)
    center_prefs = SeatPrefs(seats_needed=2, column_zone="center")
    center_groups = find_seat_groups(layout, center_prefs)

    for g in center_groups:
        # Col indices should fall into middle 40% (30% to 70% of 9 -> col index 3 to 6)
        for s in g.seats:
            frac = s.col_index / 9.0
            assert 0.30 <= frac <= 0.70


def test_seat_category_and_max_price():
    layout = _build_test_layout(rows=9, cols=10)
    prefs = SeatPrefs(
        seats_needed=2,
        seat_category="Recliner",
        max_price_per_seat=700.0,
    )
    groups = find_seat_groups(layout, prefs)
    assert len(groups) > 0
    assert all(g.category == "Recliner" for g in groups)
    assert all(g.avg_price <= 700.0 for g in groups)

    # If max_price is lower than recliner price (600), should return 0 groups
    low_price_prefs = SeatPrefs(
        seats_needed=2,
        seat_category="Recliner",
        max_price_per_seat=400.0,
    )
    assert len(find_seat_groups(layout, low_price_prefs)) == 0


def test_orphan_seat_penalty_ranks_cleaner_group_higher():
    layout = _build_test_layout(rows=3, cols=6)
    # Row 0: seats (0, 0) and (0, 1) are booked
    # (0, 2) available
    # (0, 3), (0, 4) available
    # (0, 5) booked
    # If user takes (0, 3) and (0, 4), seat (0, 2) is left as a lone orphan between (0, 1 booked) and (0, 3)!
    grid = layout.get_grid()
    grid[(0, 0)].status = SeatStatus.BOOKED
    grid[(0, 1)].status = SeatStatus.BOOKED
    grid[(0, 5)].status = SeatStatus.BOOKED

    # In Row 1: all 6 seats are available, so choosing (1, 2), (1, 3) leaves 2 on each side (no single orphan)
    prefs = SeatPrefs(seats_needed=2, must_be_consecutive=True)
    groups = find_seat_groups(layout, prefs)

    # Top group should not be the one leaving a single orphan
    top_group = groups[0]
    assert top_group.row_label != "A"  # Row A had the orphan condition


def test_generate_text_seat_map():
    from ticketnotify.engine.seat_engine import generate_text_seat_map

    layout = _build_test_layout(rows=6, cols=8)
    map_str = generate_text_seat_map(layout)
    assert "SCREEN THIS WAY" in map_str
    assert "FRONT THIRD" in map_str
    assert "MIDDLE THIRD" in map_str
    assert "BACK THIRD" in map_str
    assert "[A1]" in map_str


def test_match_exact_seats_all_available():
    from ticketnotify.engine.seat_engine import match_exact_seats

    layout = _build_test_layout(rows=6, cols=8)
    # Target seats: C3, C4, C5
    all_matched, matched, alternatives = match_exact_seats(layout, ["C3", "C4", "C5"])
    assert all_matched is True
    assert len(matched) == 3
    assert [s.seat_label for s in matched] == ["C3", "C4", "C5"]
    assert len(alternatives) == 0


def test_match_exact_seats_with_fallback_alternatives():
    from ticketnotify.engine.seat_engine import match_exact_seats

    layout = _build_test_layout(rows=6, cols=8)
    grid = layout.get_grid()
    # Book C4
    grid[(2, 3)].status = SeatStatus.BOOKED  # C4 is row 2, col 3

    all_matched, matched, alternatives = match_exact_seats(layout, ["C3", "C4", "C5"])
    assert all_matched is False
    assert len(matched) == 2  # C3 and C5 are available, but C4 is booked
    # Falls back to nearest alternative groups
    assert len(alternatives) > 0
    assert len(alternatives[0].seat_labels) == 3


@pytest.mark.asyncio
async def test_screen_layout_cache_db():
    from ticketnotify.database.session import init_db, get_db_session
    from ticketnotify.database.crud import save_screen_layout, get_cached_screen_layout

    await init_db()
    async with get_db_session() as session:
        layout_dict = {
            "total_rows": 5,
            "total_cols": 8,
            "screen_name": "Audi 1",
            "categories": {"Prime": 250.0},
        }
        await save_screen_layout(session, "pvrinox", "PVR_VEL_01", "Audi 1", layout_dict)
        retrieved = await get_cached_screen_layout(session, "pvrinox", "PVR_VEL_01", "Audi 1")
        assert retrieved is not None
        assert retrieved["screen_name"] == "Audi 1"
        assert retrieved["total_rows"] == 5

