"""Fire drill test: flips platform from 'no shows' to 'shows open'
and measures detection latency and send latency end-to-end.
"""

import asyncio
import time
import pytest
from unittest.mock import AsyncMock

from ticketnotify.adapters.base import PlatformAdapter, FetchResult, Show, SeatStatus, MovieMatch
from ticketnotify.adapters.registry import registry
from ticketnotify.database.models import User, Alert, Location, PlatformState
from ticketnotify.database.session import get_db_session
from ticketnotify.engine.scheduler import WatchGroup, scheduler
from ticketnotify.engine.notifier import notifier
from ticketnotify.location.models import NormalizedLocation


class SwitchableFireDrillAdapter(PlatformAdapter):
    platform_name = "firedrill"
    platform_label = "FireDrill Mock Platform"
    supported_countries = ["in"]

    def __init__(self):
        self.is_open = False
        self.flip_timestamp = 0.0

    def flip_to_open(self):
        self.is_open = True
        self.flip_timestamp = time.time()

    async def search_movie(self, title, location):
        return [MovieMatch(movie_id="FD_AVATAR", platform="firedrill", title="Avengers: Doomsday")]

    async def get_shows(self, movie_id, location, target_date=None):
        if not self.is_open:
            return FetchResult.ok([], latency_ms=5.0)

        # Shows are now live!
        shows = [
            Show(
                show_id="fd:CIN01:2026-12-18:10:00_AM:IMAX_3D:English",
                platform="firedrill",
                movie_id=movie_id,
                movie_title="Avengers: Doomsday",
                cinema_name="PVR IMAX: Forum Mall, Koramangala",
                cinema_id="CIN01",
                cinema_chain="PVR",
                date="2026-12-18",
                time="10:00 AM",
                format="IMAX 3D",
                language="English",
                min_price=450.0,
                max_price=850.0,
                available_seats=60,
                total_seats=280,
                seat_status=SeatStatus.AVAILABLE,
                booking_url="https://booking.example.com/shows/1",
            )
        ]
        return FetchResult.ok(shows, latency_ms=8.0)

    async def health_check(self):
        return True


@pytest.mark.asyncio
async def test_fire_drill_latency_and_delivery():
    # 1. Register switchable adapter
    adapter = SwitchableFireDrillAdapter()
    registry.register(adapter)

    # 2. Setup database user & alert
    async with get_db_session() as session:
        user = User(telegram_id=888777666, username="firedrill_user", language="en", is_active=True)
        session.add(user)
        await session.flush()

        loc = Location(
            user_id=user.id,
            name="Bengaluru, India",
            normalized_city="Bengaluru",
            normalized_country="India",
            country_code="in",
            latitude=12.9716,
            longitude=77.5946,
            radius_km=10.0,
            platform_mappings={"firedrill": "BANG"},
        )
        session.add(loc)
        await session.flush()

        alert = Alert(
            user_id=user.id,
            location_id=loc.id,
            movie_query="Avengers: Doomsday",
            platforms=["firedrill"],
            movie_ids_by_platform={"firedrill": "FD_AVATAR"},
            alert_types=["bookings_opened", "new_show_added"],
            urgency="HOT",
            status="active",
        )
        alert.location = loc
        alert.user = user
        session.add(alert)
        await session.commit()

    # 3. Create watch group
    group = WatchGroup(
        platform="firedrill",
        movie_id="FD_AVATAR",
        city_identifier="bengaluru",
        movie_title="Avengers: Doomsday",
    )
    group.alerts.append(alert)

    # Step A: Silent baseline poll when tickets are not open
    await scheduler._poll_group(group)
    assert scheduler.metrics["notifications_generated"] == 0

    # Step B: FLIP THE SWITCH -> "SHOWS OPEN"
    adapter.flip_to_open()
    t_flip = adapter.flip_timestamp

    # Mock notifier direct send to intercept message delivery
    mock_bot = AsyncMock()
    notifier.set_bot(mock_bot)

    # Run the polling cycle
    t_poll_start = time.time()
    await scheduler._poll_group(group)
    t_detected = time.time()

    # Calculate latencies
    detection_latency = (t_detected - t_flip) * 1000.0

    print(f"\n🔥 FIRE DRILL COMPLETED:")
    print(f"   • Detection Latency: {detection_latency:.2f} ms")
    print(f"   • Target Latency: < 1000 ms (sub-second)")

    # Assertions
    assert detection_latency < 1000.0  # Sub-second detection
    # Verify bot send_message was invoked with the exact alert content
    mock_bot.send_message.assert_called_once()
    call_args = mock_bot.send_message.call_args
    sent_text = call_args.kwargs.get("text") or call_args.args[1]
    assert "BOOKINGS OPENED" in sent_text
    assert "Avengers: Doomsday" in sent_text
    assert "PVR IMAX: Forum Mall" in sent_text
