"""Seat preference engine for intelligent seat group matching and scoring."""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Dict, Any, Tuple


class SeatStatus(str, Enum):
    AVAILABLE = "available"
    BOOKED = "booked"
    BLOCKED = "blocked"


@dataclass
class Seat:
    row_index: int
    col_index: int
    row_label: str
    seat_label: str
    status: str = SeatStatus.AVAILABLE
    category: str = "Standard"
    price: float = 250.0
    is_aisle: bool = False

    @property
    def is_available(self) -> bool:
        return self.status == SeatStatus.AVAILABLE


@dataclass
class SeatLayout:
    total_rows: int
    total_cols: int
    seats: List[Seat] = field(default_factory=list)
    screen_name: str = "Screen 1"

    def get_grid(self) -> Dict[Tuple[int, int], Seat]:
        return {(s.row_index, s.col_index): s for s in self.seats}


@dataclass
class SeatPrefs:
    seats_needed: int = 1
    must_be_consecutive: bool = True
    row_zone: str = "any"  # front | middle | back | any
    column_zone: str = "any"  # center | left | right | corner | aisle | any
    seat_category: str = "any"  # Recliner | Premium | Gold | Silver | any
    max_price_per_seat: Optional[float] = None


@dataclass
class SeatGroup:
    seats: List[Seat]
    score: float
    row_label: str
    seat_labels: List[str]
    category: str
    avg_price: float
    total_price: float

    @property
    def description(self) -> str:
        seats_str = ", ".join(self.seat_labels)
        return (
            f"Row {self.row_label} ({seats_str}) - {self.category} - "
            f"₹{int(self.avg_price)}/seat (Score: {self.score:.1f})"
        )


def _matches_row_zone(row_idx: int, total_rows: int, zone: str) -> bool:
    if zone == "any" or total_rows <= 0:
        return True
    third = total_rows / 3.0
    if zone == "front":
        return row_idx < third
    elif zone == "middle":
        return third <= row_idx < 2.0 * third
    elif zone == "back":
        return row_idx >= 2.0 * third
    return True


def _matches_column_zone(seat: Seat, total_cols: int, zone: str, grid: Dict[Tuple[int, int], Seat]) -> bool:
    if zone == "any" or total_cols <= 0:
        return True
    
    col_idx = seat.col_index
    frac = col_idx / float(max(1, total_cols - 1))

    if zone == "center":
        # Middle ~40% of columns: 30% to 70%
        return 0.30 <= frac <= 0.70
    elif zone == "left":
        # Leftmost 30%
        return frac < 0.30
    elif zone == "right":
        # Rightmost 30%
        return frac > 0.70
    elif zone == "corner":
        # Leftmost or rightmost 15%
        return frac <= 0.15 or frac >= 0.85
    elif zone == "aisle":
        if seat.is_aisle:
            return True
        # Check if adjacent col is empty/gap
        left_empty = (seat.row_index, seat.col_index - 1) not in grid
        right_empty = (seat.row_index, seat.col_index + 1) not in grid
        return left_empty or right_empty

    return True


def _matches_category(seat: Seat, category_pref: str) -> bool:
    if category_pref == "any":
        return True
    return category_pref.lower() in seat.category.lower()


def _calculate_orphan_penalty(group: List[Seat], grid: Dict[Tuple[int, int], Seat]) -> float:
    """
    Penalizes leaving a single lone unbooked seat (orphan) next to this group.
    """
    if not group:
        return 0.0
    row_idx = group[0].row_index
    col_indices = [s.col_index for s in group]
    min_col = min(col_indices)
    max_col = max(col_indices)

    penalty = 0.0

    # Check left side: is min_col - 1 available AND min_col - 2 booked/blocked/boundary?
    left_seat = grid.get((row_idx, min_col - 1))
    if left_seat and left_seat.is_available:
        left_two = grid.get((row_idx, min_col - 2))
        if left_two is None or not left_two.is_available:
            penalty += 20.0  # Left 1 orphan seat!

    # Check right side: is max_col + 1 available AND max_col + 2 booked/blocked/boundary?
    right_seat = grid.get((row_idx, max_col + 1))
    if right_seat and right_seat.is_available:
        right_two = grid.get((row_idx, max_col + 2))
        if right_two is None or not right_two.is_available:
            penalty += 20.0  # Right 1 orphan seat!

    return penalty


def _score_seat_group(
    group: List[Seat],
    layout: SeatLayout,
    prefs: SeatPrefs,
    grid: Dict[Tuple[int, int], Seat],
) -> float:
    """
    Computes a matching score based on distance from center, row zone preference,
    category alignment, and orphan seat avoidance.
    """
    base_score = 100.0
    total_rows = layout.total_rows
    total_cols = layout.total_cols

    mid_row = (total_rows - 1) / 2.0 if total_rows > 1 else 0.0
    mid_col = (total_cols - 1) / 2.0 if total_cols > 1 else 0.0

    avg_row = sum(s.row_index for s in group) / float(len(group))
    avg_col = sum(s.col_index for s in group) / float(len(group))

    # Center-of-screen bonus: closer to middle row & middle col is better
    row_dist_ratio = abs(avg_row - mid_row) / max(1.0, float(total_rows))
    col_dist_ratio = abs(avg_col - mid_col) / max(1.0, float(total_cols))

    center_bonus = (1.0 - (row_dist_ratio * 0.4 + col_dist_ratio * 0.6)) * 40.0
    base_score += center_bonus

    # Category bonus
    if prefs.seat_category != "any":
        if any(prefs.seat_category.lower() in s.category.lower() for s in group):
            base_score += 15.0

    # Zone alignment bonus
    if prefs.row_zone != "any" and _matches_row_zone(int(avg_row), total_rows, prefs.row_zone):
        base_score += 15.0

    if prefs.column_zone != "any" and any(_matches_column_zone(s, total_cols, prefs.column_zone, grid) for s in group):
        base_score += 15.0

    # Orphan seat penalty
    orphan_pen = _calculate_orphan_penalty(group, grid)
    base_score -= orphan_pen

    return max(0.0, base_score)


def find_seat_groups(layout: SeatLayout, prefs: SeatPrefs) -> List[SeatGroup]:
    """
    PURE function finding and ranking available seat groups matching user preferences.
    """
    if layout.total_rows <= 0 or layout.total_cols <= 0 or prefs.seats_needed <= 0:
        return []

    grid = layout.get_grid()
    needed = prefs.seats_needed
    groups: List[SeatGroup] = []

    # Organize seats by row index
    seats_by_row: Dict[int, List[Seat]] = {}
    for s in layout.seats:
        seats_by_row.setdefault(s.row_index, []).append(s)

    for r_idx in sorted(seats_by_row.keys()):
        # Filter by row zone first
        if not _matches_row_zone(r_idx, layout.total_rows, prefs.row_zone):
            continue

        row_seats = sorted(seats_by_row[r_idx], key=lambda x: x.col_index)

        # Filter seats satisfying category, price, and column zone
        candidate_seats = []
        for s in row_seats:
            if not s.is_available:
                continue
            if prefs.max_price_per_seat is not None and s.price > prefs.max_price_per_seat:
                continue
            if not _matches_category(s, prefs.seat_category):
                continue
            if prefs.column_zone not in ("any", "aisle") and not _matches_column_zone(s, layout.total_cols, prefs.column_zone, grid):
                continue
            candidate_seats.append(s)

        if len(candidate_seats) < needed:
            continue

        if prefs.must_be_consecutive:
            # Find contiguous runs where col_index is strictly consecutive
            for i in range(len(candidate_seats) - needed + 1):
                window = candidate_seats[i : i + needed]
                # If aisle requested, at least one seat in the group must touch an aisle
                if prefs.column_zone == "aisle" and not any(_matches_column_zone(s, layout.total_cols, "aisle", grid) for s in window):
                    continue
                # Verify consecutive column indices
                is_consecutive = True
                for j in range(len(window) - 1):
                    if window[j + 1].col_index != window[j].col_index + 1:
                        is_consecutive = False
                        break

                if is_consecutive:
                    score = _score_seat_group(window, layout, prefs, grid)
                    cat = window[0].category
                    avg_p = sum(s.price for s in window) / float(len(window))
                    tot_p = sum(s.price for s in window)
                    groups.append(
                        SeatGroup(
                            seats=window,
                            score=score,
                            row_label=window[0].row_label,
                            seat_labels=[s.seat_label for s in window],
                            category=cat,
                            avg_price=avg_p,
                            total_price=tot_p,
                        )
                    )
        else:
            # Non-consecutive: pick best window of N candidate seats in this row
            for i in range(len(candidate_seats) - needed + 1):
                window = candidate_seats[i : i + needed]
                if prefs.column_zone == "aisle" and not any(_matches_column_zone(s, layout.total_cols, "aisle", grid) for s in window):
                    continue
                score = _score_seat_group(window, layout, prefs, grid)
                cat = window[0].category
                avg_p = sum(s.price for s in window) / float(len(window))
                tot_p = sum(s.price for s in window)
                groups.append(
                    SeatGroup(
                        seats=window,
                        score=score,
                        row_label=window[0].row_label,
                        seat_labels=[s.seat_label for s in window],
                        category=cat,
                        avg_price=avg_p,
                        total_price=tot_p,
                    )
                )

    # Sort descending by score
    groups.sort(key=lambda g: g.score, reverse=True)
    return groups
