"""Tests ensuring failed polls never trigger false alerts or overwrite state snapshots."""

import pytest
from unittest.mock import AsyncMock, patch

from ticketnotify.adapters.base import FetchResult, FetchStatus, Show, SeatStatus
from ticketnotify.database.models import User, Location, Alert, PlatformState
from ticketnotify.engine.scheduler import AdaptiveScheduler, WatchGroup
from ticketnotify.adapters.registry import registry


@pytest.mark.asyncio
async def test_failed_poll_never_produces_alerts_or_overwrites_snapshot():
    scheduler = AdaptiveScheduler()

    # Create dummy alert & location
    dummy_loc = Location(
        id=1,
        user_id=1,
        name="Bengaluru",
        normalized_city="Bengaluru",
        normalized_country="India",
        country_code="in",
        latitude=12.9716,
        longitude=77.5946,
        platform_mappings={"bms": "BANG"},
    )
    dummy_alert = Alert(
        id=42,
        user_id=1,
        movie_query="Avatar",
        location_id=1,
        platforms=["bms"],
        movie_ids_by_platform={"bms": "ET001"},
        filters_json={},
        alert_types=["bookings_opened", "new_show_added"],
        status="active",
        location=dummy_loc,
    )

    group = WatchGroup(
        platform="bms",
        movie_id="ET001",
        city_identifier="Bengaluru",
        movie_title="Avatar",
    )
    group.alerts.append(dummy_alert)

    # Mock DB platform state with existing snapshot
    dummy_state = PlatformState(
        id=10,
        alert_key=group.key,
        platform="bms",
        movie_identifier="ET001",
        city_identifier="Bengaluru",
        last_snapshot_hash="original_snapshot_hash_123",
        last_snapshot_data={"shows": {"old_show_1": {}}},
        consecutive_failures=0,
    )

    # 1. Simulate platform returning BLOCKED (e.g. 403 / Cloudflare)
    with patch.object(
        registry,
        "get_shows",
        new=AsyncMock(return_value=FetchResult.blocked("Cloudflare challenge 403")),
    ), patch(
        "ticketnotify.engine.scheduler.get_or_create_platform_state",
        new=AsyncMock(return_value=dummy_state),
    ), patch(
        "ticketnotify.engine.scheduler.update_platform_state_snapshot",
        new=AsyncMock(),
    ) as mock_update_snapshot, patch(
        "ticketnotify.engine.scheduler.record_platform_state_failure",
        new=AsyncMock(),
    ) as mock_record_failure, patch(
        "ticketnotify.engine.scheduler.notifier.enqueue",
        new=AsyncMock(),
    ) as mock_enqueue:

        await scheduler._poll_group(group)

        # Snapshot must NOT be overwritten
        mock_update_snapshot.assert_not_called()
        assert dummy_state.last_snapshot_hash == "original_snapshot_hash_123"

        # Notifier must NOT be called (zero false alerts)
        mock_enqueue.assert_not_called()

        # Failure must be recorded
        mock_record_failure.assert_called_once()

    # 2. Simulate platform returning UNAVAILABLE (e.g. DNS / Connection timeout)
    with patch.object(
        registry,
        "get_shows",
        new=AsyncMock(return_value=FetchResult.unavailable("Connection timeout")),
    ), patch(
        "ticketnotify.engine.scheduler.get_or_create_platform_state",
        new=AsyncMock(return_value=dummy_state),
    ), patch(
        "ticketnotify.engine.scheduler.update_platform_state_snapshot",
        new=AsyncMock(),
    ) as mock_update_snapshot, patch(
        "ticketnotify.engine.scheduler.record_platform_state_failure",
        new=AsyncMock(),
    ) as mock_record_failure, patch(
        "ticketnotify.engine.scheduler.notifier.enqueue",
        new=AsyncMock(),
    ) as mock_enqueue:

        await scheduler._poll_group(group)

        mock_update_snapshot.assert_not_called()
        mock_enqueue.assert_not_called()
        mock_record_failure.assert_called_once()
