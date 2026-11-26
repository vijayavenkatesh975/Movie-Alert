"""Unit tests for DiffEngine and filter matching."""

import pytest
from ticketnotify.adapters.base import Show, SeatStatus
from ticketnotify.database.models import Alert, Location
from ticketnotify.engine.diff_engine import DiffEngine


@pytest.fixture
def base_show():
    return Show(
        show_id="bms:PVR01:2026-11-25:10:30_AM:IMAX_3D:English",
        platform="bms",
        movie_id="ET100",
        movie_title="Avatar: Fire and Ash",
        cinema_name="PVR IMAX: Forum Mall",
        cinema_id="PVR01",
        cinema_chain="PVR",
        latitude=12.9352,
        longitude=77.6111,
        date="2026-11-25",
        time="10:30 AM",
        format="IMAX 3D",
        language="English",
        min_price=450.0,
        max_price=850.0,
        available_seats=150,
        total_seats=280,
        seat_status=SeatStatus.AVAILABLE,
        booking_url="https://in.bookmyshow.com/buytickets/ET100/bang",
    )


def test_diff_bookings_opened(base_show):
    old_snapshot = {"shows": {}}
    new_shows = [base_show]

    events = DiffEngine.diff(old_snapshot, new_shows, "bms", "ET100")
    event_types = [e.event_type for e in events]
    assert "bookings_opened" in event_types
    assert "new_show_added" in event_types


def test_diff_seats_filling_fast(base_show):
    old_snapshot = {
        "shows": {
            base_show.show_id: {
                "seat_status": SeatStatus.AVAILABLE,
                "min_price": 450.0,
                "available_seats": 150,
            }
        }
    }
    updated_show = base_show.model_copy(update={"seat_status": SeatStatus.FILLING_FAST, "available_seats": 35})
    new_shows = [updated_show]

    events = DiffEngine.diff(old_snapshot, new_shows, "bms", "ET100")
    assert len(events) == 1
    assert events[0].event_type == "seats_filling_fast"
    assert "Seats filling fast" in events[0].summary


def test_diff_price_drop(base_show):
    old_snapshot = {
        "shows": {
            base_show.show_id: {
                "seat_status": SeatStatus.AVAILABLE,
                "min_price": 500.0,
            }
        }
    }
    updated_show = base_show.model_copy(update={"min_price": 350.0})
    new_shows = [updated_show]

    events = DiffEngine.diff(old_snapshot, new_shows, "bms", "ET100")
    assert len(events) == 1
    assert events[0].event_type == "price_drop"
    assert "Price dropped" in events[0].summary


def test_matches_alert_filters_format(base_show):
    loc = Location(latitude=12.9716, longitude=77.5946, radius_km=25.0)

    # Alert looking for IMAX
    alert_imax = Alert(
        filters_json={"formats": ["IMAX", "4DX"]},
        location=loc,
    )
    assert DiffEngine.matches_alert_filters(base_show, alert_imax) is True

    # Alert looking for 2D only
    alert_2d = Alert(
        filters_json={"formats": ["2D"]},
        location=loc,
    )
    assert DiffEngine.matches_alert_filters(base_show, alert_2d) is False


def test_matches_alert_filters_price_and_seats(base_show):
    loc = Location(latitude=12.9716, longitude=77.5946, radius_km=25.0)

    # Max price 500, min seats 2 (show is 450, 150 seats) -> True
    alert_ok = Alert(
        filters_json={"max_price": 500, "min_seats": 2},
        location=loc,
    )
    assert DiffEngine.matches_alert_filters(base_show, alert_ok) is True

    # Max price 300 -> False
    alert_too_expensive = Alert(
        filters_json={"max_price": 300},
        location=loc,
    )
    assert DiffEngine.matches_alert_filters(base_show, alert_too_expensive) is False
