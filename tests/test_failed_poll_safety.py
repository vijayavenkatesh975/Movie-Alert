"""Test proving that failed polls (Blocked, Unavailable, ParseError) never overwrite state or trigger false alerts."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from ticketnotify.adapters.base import FetchResult, FetchStatus, Show, SeatStatus
from ticketnotify.database.models import Alert, User, Location, PlatformState
from ticketnotify.engine.scheduler import WatchGroup, AdaptiveScheduler


@pytest.mark.asyncio
async def test_failed_poll_preserves_state_and_sends_no_alerts():
    scheduler = AdaptiveScheduler()

    # Create dummy alert
    user = User(id=1, telegram_id=12345678, username="test_user")
    loc = Location(
        id=1,
        user_id=1,
        name="Bengaluru",
        normalized_city="Bengaluru",
        normalized_country="India",
        country_code="in",
        latitude=12.9716,
        longitude=77.5946,
    )
    alert = Alert(
        id=10,
        user_id=1,
        movie_query="Avatar",
        location_id=1,
        platforms=["bms"],
        alert_types=["bookings_opened", "new_show_added"],
    )
    alert.user = user
    alert.location = loc

    group = WatchGroup(
        platform="bms",
        movie_id="ET001",
        city_identifier="bengaluru",
        movie_title="Avatar",
    )
    group.alerts.append(alert)

    # Initial snapshot
    initial_snapshot_data = {
        "shows": {
            "s1": {
                "show_id": "s1",
                "platform": "bms",
                "movie_id": "ET001",
                "movie_title": "Avatar",
                "cinema_name": "PVR Forum",
                "cinema_id": "PVR01",
                "date": "2026-12-18",
                "time": "10:00 AM",
                "min_price": 300.0,
                "max_price": 500.0,
                "available_seats": 50,
                "seat_status": "available",
            }
        }
    }
    initial_hash = "initial_valid_hash_123"

    mock_state = MagicMock(spec=PlatformState)
    mock_state.id = 1
    mock_state.last_snapshot_hash = initial_hash
    mock_state.last_snapshot_data = initial_snapshot_data
    mock_state.consecutive_failures = 0

    # Test each failure status
    failure_results = [
        FetchResult.blocked("Cloudflare 403 Forbidden"),
        FetchResult.unavailable("Connection refused (ECONNREFUSED)"),
        FetchResult.parse_error("Invalid JSON payload from scraper"),
    ]

    # Mock DB session context manager
    mock_db_session = AsyncMock()
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_db_session)
    mock_cm.__aexit__ = AsyncMock(return_value=None)

    for fail_res in failure_results:
        with patch("ticketnotify.engine.scheduler.get_db_session", return_value=mock_cm), \
             patch("ticketnotify.engine.scheduler.registry.is_platform_available", return_value=True), \
             patch("ticketnotify.engine.scheduler.registry.get_shows", new_callable=AsyncMock) as mock_get_shows, \
             patch("ticketnotify.engine.scheduler.get_or_create_platform_state", new_callable=AsyncMock) as mock_get_state, \
             patch("ticketnotify.engine.scheduler.record_platform_state_failure", new_callable=AsyncMock) as mock_record_fail, \
             patch("ticketnotify.engine.scheduler.update_platform_state_snapshot", new_callable=AsyncMock) as mock_update_snap, \
             patch("ticketnotify.engine.scheduler.notifier.enqueue", new_callable=AsyncMock) as mock_enqueue:

            mock_get_shows.return_value = fail_res
            mock_get_state.return_value = mock_state

            await scheduler._poll_group(group)

            # Assert failure was recorded
            mock_record_fail.assert_called_once()
            # Assert state snapshot was NEVER overwritten
            mock_update_snap.assert_not_called()
            # Assert no alerts were ever enqueued
            mock_enqueue.assert_not_called()
            # Assert hash remains intact
            assert mock_state.last_snapshot_hash == initial_hash
