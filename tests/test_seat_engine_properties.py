"""Property-based unit tests for seat engine consistency across 1-10 seats,
row zones, column zones, consecutive requirements, and pricing.
"""

import pytest
from ticketnotify.engine.seat_engine import (
    Seat,
    SeatLayout,
    SeatPrefs,
    SeatStatus,
    find_seat_groups,
)


def make_variable_layout(num_rows: int = 12, num_cols: int = 16) -> SeatLayout:
    seats = []
    labels = ["A", "B", "C", "D", "E", "F", "G", "H", "J", "K", "L", "M"]
    for r in range(num_rows):
        r_label = labels[r % len(labels)]
        category = "Recliner" if r >= 10 else ("Premium" if r >= 6 else "Standard")
        price = 650.0 if category == "Recliner" else (350.0 if category == "Premium" else 200.0)
        for c in range(num_cols):
            # Introduce an aisle gap between col 5 and 6
            if c == 5:
                continue
            is_aisle = c in (4, 6, 0, num_cols - 1)
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
    return SeatLayout(total_rows=num_rows, total_cols=num_cols, seats=seats)


@pytest.mark.parametrize("seats_needed", list(range(1, 11)))
def test_all_seat_sizes_1_to_10_consecutive(seats_needed: int):
    layout = make_variable_layout(num_rows=12, num_cols=16)
    prefs = SeatPrefs(
        seats_needed=seats_needed,
        must_be_consecutive=True,
        row_zone="any",
        column_zone="any",
    )
    groups = find_seat_groups(layout, prefs)
    assert len(groups) > 0

    for g in groups:
        # 1. Exact size
        assert len(g.seats) == seats_needed
        # 2. All available
        assert all(s.is_available for s in g.seats)
        # 3. Same row
        assert len(set(s.row_index for s in g.seats)) == 1
        # 4. Strictly consecutive column indices
        cols = [s.col_index for s in g.seats]
        for idx in range(len(cols) - 1):
            assert cols[idx + 1] == cols[idx] + 1


@pytest.mark.parametrize("row_zone", ["front", "middle", "back"])
def test_row_zone_properties(row_zone: str):
    layout = make_variable_layout(num_rows=12, num_cols=16)
    prefs = SeatPrefs(seats_needed=3, row_zone=row_zone)
    groups = find_seat_groups(layout, prefs)
    assert len(groups) > 0

    for g in groups:
        r_idx = g.seats[0].row_index
        if row_zone == "front":
            assert r_idx < 4  # 12 / 3 = 4
        elif row_zone == "middle":
            assert 4 <= r_idx < 8
        elif row_zone == "back":
            assert r_idx >= 8


@pytest.mark.parametrize("column_zone", ["center", "left", "right", "corner", "aisle"])
def test_column_zone_properties(column_zone: str):
    layout = make_variable_layout(num_rows=12, num_cols=16)
    prefs = SeatPrefs(seats_needed=2, column_zone=column_zone)
    groups = find_seat_groups(layout, prefs)
    assert len(groups) > 0

    grid = layout.get_grid()
    for g in groups:
        if column_zone == "aisle":
            assert any(s.is_aisle or (s.row_index, s.col_index - 1) not in grid or (s.row_index, s.col_index + 1) not in grid for s in g.seats)
        else:
            for s in g.seats:
                frac = s.col_index / 15.0
                if column_zone == "center":
                    assert 0.30 <= frac <= 0.70
                elif column_zone == "left":
                    assert frac < 0.30
                elif column_zone == "right":
                    assert frac > 0.70
                elif column_zone == "corner":
                    assert frac <= 0.15 or frac >= 0.85
