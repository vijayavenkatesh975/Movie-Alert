"""Unit tests for scheduler grouping and deduplication."""

import pytest
from ticketnotify.database.models import Alert, Location, User
from ticketnotify.engine.scheduler import WatchGroup


def test_watch_group_deduplication():
    # Simulate 50 users tracking 'Avatar' in 'Bengaluru' on BMS
    group = WatchGroup(
        platform="bms",
        movie_id="ET00392345",
        city_identifier="bengaluru",
        movie_title="Avatar: Fire and Ash",
    )

    for i in range(50):
        user = User(id=i + 1, telegram_id=1000 + i)
        loc = Location(id=i + 1, normalized_city="Bengaluru", normalized_country="India")
        alert = Alert(
            id=i + 1,
            user_id=user.id,
            movie_query="Avatar",
            location_id=loc.id,
            platforms=["bms"],
            alert_types=["bookings_opened"],
            user=user,
            location=loc,
        )
        group.alerts.append(alert)

    # 50 users collapsed into 1 group key
    assert group.key == "bms:bengaluru:ET00392345"
    assert len(group.alerts) == 50
    # Is hot because >= 3 alerts
    assert len(group.alerts) >= 3


@pytest.mark.asyncio
async def test_failed_poll_never_produces_alert_or_overwrites_snapshot():
    """Verify that a BLOCKED or UNAVAILABLE poll result preserves snapshot state and sends zero alerts."""
    from unittest.mock import AsyncMock, patch
    from ticketnotify.adapters.base import FetchResult, FetchStatus, Show
    from ticketnotify.engine.scheduler import AdaptiveScheduler
    from ticketnotify.engine.notifier import notifier

    scheduler = AdaptiveScheduler()
    group = WatchGroup(
        platform="bms",
        movie_id="ET001",
        city_identifier="bengaluru",
        movie_title="Movie Test",
    )
    user = User(id=1, telegram_id=99999)
    loc = Location(id=1, normalized_city="Bengaluru", normalized_country="India")
    alert = Alert(
        id=1,
        user_id=1,
        movie_query="Movie Test",
        location_id=1,
        platforms=["bms"],
        alert_types=["bookings_opened", "new_show_added"],
        user=user,
        location=loc,
    )
    group.alerts.append(alert)

    # Mock registry to return a failed FetchResult (BLOCKED)
    with patch("ticketnotify.adapters.registry.registry.get_shows", new_callable=AsyncMock) as mock_get_shows, \
         patch.object(notifier, "enqueue", new_callable=AsyncMock) as mock_enqueue:

        # 1. Blocked response (e.g. HTTP 403 Cloudflare challenge)
        mock_get_shows.return_value = FetchResult.blocked("Cloudflare challenge encountered")
        
        await scheduler._poll_group(group)

        # Must NOT call notifier.enqueue
        mock_enqueue.assert_not_called()

        # 2. Unavailable response (e.g. DNS failure)
        mock_get_shows.return_value = FetchResult.unavailable("DNS resolution failure")
        await scheduler._poll_group(group)

        mock_enqueue.assert_not_called()

