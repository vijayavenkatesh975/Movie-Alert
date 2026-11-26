"""Unit tests for platform adapters using recorded fixtures."""

import json
from pathlib import Path
import pytest

from ticketnotify.location.models import NormalizedLocation
from ticketnotify.adapters.bms import BookMyShowAdapter
from ticketnotify.adapters.ticketnew import TicketnewAdapter
from ticketnotify.adapters.district import DistrictAdapter
from ticketnotify.adapters.pvrinox import PvrInoxAdapter
from ticketnotify.adapters.base import SeatStatus

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_location():
    return NormalizedLocation(
        raw_query="Bengaluru",
        city="Bengaluru",
        country="India",
        country_code="in",
        latitude=12.9716,
        longitude=77.5946,
        display_name="Bengaluru, Karnataka, India",
        platform_codes={
            "bms": "BANG",
            "ticketnew": "bangalore",
            "district": "bengaluru",
            "pvrinox": "Bengaluru",
        },
        supported_platforms=["bms", "ticketnew", "district", "pvrinox"],
    )


def test_bms_parser_with_fixtures():
    adapter = BookMyShowAdapter()
    showtimes_file = FIXTURES_DIR / "bms_showtimes.json"
    with open(showtimes_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    shows = adapter._parse_bms_shows(data, "ET00392345", "BANG", "2026-11-25")
    assert len(shows) == 3

    # First show: PVR IMAX 10:30 AM
    s1 = shows[0]
    assert s1.platform == "bms"
    assert "PVR IMAX" in s1.cinema_name
    assert s1.time == "10:30 AM"
    assert s1.format == "IMAX 3D"
    assert s1.language == "English"
    assert s1.min_price == 450.0
    assert s1.max_price == 850.0
    assert s1.available_seats == 42
    assert s1.seat_status == SeatStatus.FILLING_FAST
    assert "in.bookmyshow.com" in s1.booking_url

    # Second show: PVR IMAX 02:15 PM Available
    s2 = shows[1]
    assert s2.available_seats == 180
    assert s2.seat_status == SeatStatus.AVAILABLE

    # Third show: INOX Garuda Almost Full
    s3 = shows[2]
    assert "INOX" in s3.cinema_name
    assert s3.format == "2D"
    assert s3.seat_status == SeatStatus.ALMOST_FULL


def test_ticketnew_parser_with_fixtures():
    adapter = TicketnewAdapter()
    shows_file = FIXTURES_DIR / "ticketnew_shows.json"
    with open(shows_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    shows = adapter._parse_ticketnew_shows(data, "TN_M123", "chennai", "2026-11-25")
    assert len(shows) == 1
    s = shows[0]
    assert s.platform == "ticketnew"
    assert "Sathyam" in s.cinema_name
    assert s.format == "2D"
    assert s.min_price == 180.0
    assert "ticketnew.com" in s.booking_url


def test_district_parser_with_fixtures():
    adapter = DistrictAdapter()
    shows_file = FIXTURES_DIR / "district_shows.json"
    with open(shows_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    shows = adapter._parse_district_shows(data, "DIS_M999", "bengaluru", "2026-11-25")
    assert len(shows) == 1
    s = shows[0]
    assert s.platform == "district"
    assert "Cinepolis" in s.cinema_name
    assert s.format == "IMAX 3D"
    assert s.available_seats == 60
    assert "district.in" in s.booking_url


def test_pvrinox_parser_with_fixtures():
    adapter = PvrInoxAdapter()
    shows_file = FIXTURES_DIR / "pvrinox_shows.json"
    with open(shows_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    shows = adapter._parse_pvr_shows(data, "PVR_F123", "Bengaluru", "2026-11-25")
    assert len(shows) == 1
    s = shows[0]
    assert s.platform == "pvrinox"
    assert "Forum South" in s.cinema_name
    assert s.format == "P[XL]"
    assert s.time == "06:15 PM"
    assert "pvrcinemas.com" in s.booking_url
