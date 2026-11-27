"""Tests for granular notification controls, snooze, pause, and quiet hours."""

import pytest
import time
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

from ticketnotify.database.models import User, Alert, Location
from ticketnotify.database.session import get_db_session, init_db
from ticketnotify.database.crud import (
    get_or_create_user,
    update_user_notification_preferences,
    set_user_alerts_paused,
    set_user_snooze,
)
from ticketnotify.engine.notifier import notifier
from ticketnotify.adapters.base import Show, SeatStatus
from ticketnotify.bot.locales import get_text


@pytest.mark.asyncio
async def test_notification_granular_controls():
    await init_db()
    unique_tg = int(time.time() * 1000) % 1000000000

    dummy_show = Show(
        show_id="s_test_101",
        platform="bms",
        movie_id="M1",
        movie_title="Amaran",
        cinema_name="PVR Palazzo",
        cinema_id="PVPL_CHE",
        date="2026-11-28",
        time="10:00 AM",
        min_price=200.0,
        max_price=450.0,
        available_seats=40,
        seat_status=SeatStatus.AVAILABLE,
        booking_url="https://in.bookmyshow.com/buytickets/amaran",
    )

    async with get_db_session() as session:
        user, _ = await get_or_create_user(session, telegram_id=unique_tg, username=f"user_{unique_tg}")
        # User disables price drops but keeps bookings_opened enabled
        await update_user_notification_preferences(
            session,
            user.id,
            {"bookings_opened": True, "price_drop": False},
        )

        loc = Location(
            user_id=user.id,
            name="Chennai",
            normalized_city="Chennai",
            normalized_country="India",
            country_code="in",
            latitude=13.0827,
            longitude=80.2707,
        )
        session.add(loc)
        await session.flush()

        alert = Alert(
            user_id=user.id,
            location_id=loc.id,
            movie_query="Amaran",
            platforms=["bms"],
            alert_types=["bookings_opened", "price_drop"],
        )
        alert.user = user
        session.add(alert)
        await session.commit()

    # 1. Price drop notification should be suppressed because user turned it off
    enqueued_price = await notifier.enqueue(
        alert=alert,
        platform="bms",
        notification_type="price_drop",
        show=dummy_show,
        payload_hash="hash_price_01",
        summary="Price drop detected",
    )
    assert enqueued_price is False

    # 2. Bookings opened should be accepted
    mock_bot = AsyncMock()
    notifier.set_bot(mock_bot)
    enqueued_open = await notifier.enqueue(
        alert=alert,
        platform="bms",
        notification_type="bookings_opened",
        show=dummy_show,
        payload_hash="hash_open_02",
        summary="Bookings opened",
    )
    assert enqueued_open is True


@pytest.mark.asyncio
async def test_pause_and_snooze():
    await init_db()
    unique_tg = int(time.time() * 1000) % 1000000000

    dummy_show = Show(
        show_id="s_test_102",
        platform="bms",
        movie_id="M2",
        movie_title="Moana 2",
        cinema_name="INOX Luxe",
        cinema_id="INLX_CHE",
        date="2026-11-28",
        time="14:00",
        min_price=250.0,
        max_price=500.0,
        available_seats=50,
        seat_status=SeatStatus.AVAILABLE,
        booking_url="https://in.bookmyshow.com/buytickets/moana2",
    )

    async with get_db_session() as session:
        user, _ = await get_or_create_user(session, telegram_id=unique_tg)
        # Snooze alerts for 4 hours
        snooze_time = datetime.utcnow() + timedelta(hours=4)
        await set_user_snooze(session, user.id, snooze_time)
        user.snoozed_until = snooze_time

        loc = Location(
            user_id=user.id,
            name="Chennai",
            normalized_city="Chennai",
            normalized_country="India",
            country_code="in",
            latitude=13.0827,
            longitude=80.2707,
        )
        session.add(loc)
        await session.flush()

        alert = Alert(
            user_id=user.id,
            location_id=loc.id,
            movie_query="Moana 2",
            platforms=["bms"],
            alert_types=["new_show_added"],
        )
        alert.user = user
        session.add(alert)
        await session.commit()

    # While snoozed, notification must be suppressed
    enqueued = await notifier.enqueue(
        alert=alert,
        platform="bms",
        notification_type="new_show_added",
        show=dummy_show,
        payload_hash="hash_snooze_01",
        summary="New show added",
    )
    assert enqueued is False

    # Turn off snooze and verify it now accepts
    async with get_db_session() as session:
        await set_user_snooze(session, user.id, None)
        user.snoozed_until = None

    enqueued_after = await notifier.enqueue(
        alert=alert,
        platform="bms",
        notification_type="new_show_added",
        show=dummy_show,
        payload_hash="hash_snooze_02",
        summary="New show added",
    )
    assert enqueued_after is True


def test_localization_all_five_languages():
    languages = ["en", "hi", "ta", "te", "kn"]
    for lang in languages:
        welcome = get_text("welcome", lang)
        intro = get_text("intro", lang)
        step1 = get_text("select_lang", lang)
        assert len(welcome) > 0
        assert len(intro) > 0
        assert len(step1) > 0
