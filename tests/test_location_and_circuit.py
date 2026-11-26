"""Unit tests for location geocoding, radius calculations, and circuit breaker."""

import pytest
from ticketnotify.location.distance import haversine_distance_km, is_within_radius
from ticketnotify.location.matcher import map_location_to_platforms
from ticketnotify.location.models import NormalizedLocation
from ticketnotify.adapters.circuit_breaker import PlatformCircuitBreaker, CircuitState


def test_haversine_distance():
    # Distance between Bengaluru (12.9716, 77.5946) and Forum Mall Koramangala (12.9352, 77.6111) is ~4.4 km
    dist = haversine_distance_km(12.9716, 77.5946, 12.9352, 77.6111)
    assert 3.5 < dist < 5.5
    assert is_within_radius(12.9716, 77.5946, 12.9352, 77.6111, max_radius_km=10.0) is True
    assert is_within_radius(12.9716, 77.5946, 12.9352, 77.6111, max_radius_km=2.0) is False


def test_location_matcher_operating_countries():
    # India location: all 4 platforms supported
    in_loc = NormalizedLocation(
        raw_query="Bengaluru",
        city="Bengaluru",
        country="India",
        country_code="in",
        latitude=12.9716,
        longitude=77.5946,
        display_name="Bengaluru, India",
    )
    in_loc = map_location_to_platforms(in_loc)
    assert "bms" in in_loc.supported_platforms
    assert "ticketnew" in in_loc.supported_platforms
    assert "district" in in_loc.supported_platforms
    assert "pvrinox" in in_loc.supported_platforms
    assert len(in_loc.unsupported_platforms) == 0

    # US location: BMS, Ticketnew, District, PVR not in US
    us_loc = NormalizedLocation(
        raw_query="New York",
        city="New York",
        country="United States",
        country_code="us",
        latitude=40.7128,
        longitude=-74.0060,
        display_name="New York, USA",
    )
    us_loc = map_location_to_platforms(us_loc)
    assert len(us_loc.supported_platforms) == 0
    assert "bms" in us_loc.unsupported_platforms
    assert "ticketnew" in us_loc.unsupported_platforms


def test_circuit_breaker_tripping_and_recovery():
    import time

    def _drive(coro):
        try:
            coro.send(None)
        except StopIteration:
            pass

    tripped_alert = []

    async def alert_callback(platform, msg):
        tripped_alert.append((platform, msg))

    cb = PlatformCircuitBreaker(
        platform_name="bms",
        max_failures=3,
        reset_timeout=60.0,
        on_break_callback=alert_callback,
    )

    assert cb.state == CircuitState.CLOSED
    assert cb.can_execute() is True

    # Record 2 failures -> still CLOSED
    _drive(cb.record_failure(Exception("HTTP 500")))
    _drive(cb.record_failure(Exception("HTTP 502")))
    assert cb.state == CircuitState.CLOSED
    assert cb.can_execute() is True

    # 3rd failure -> TRIPS to OPEN!
    _drive(cb.record_failure(Exception("HTTP 503 Service Unavailable")))
    assert cb.state == CircuitState.OPEN
    assert cb.can_execute() is False
    assert len(tripped_alert) == 1
    assert tripped_alert[0][0] == "bms"

    # Fast-forward time past reset timeout
    cb.last_failure_time = time.time() - 100.0

    # Cooldown elapsed -> enters HALF_OPEN
    assert cb.can_execute() is True
    assert cb.state == CircuitState.HALF_OPEN

    # Successful probe -> recovers to CLOSED
    _drive(cb.record_success())
    assert cb.state == CircuitState.CLOSED
    assert cb.failure_count == 0
