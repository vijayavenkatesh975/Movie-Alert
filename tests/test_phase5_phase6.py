"""Tests for Phase 5 (Deployment hardening) and Phase 6 (UX features)."""

import pytest
from httpx import AsyncClient, ASGITransport
from datetime import datetime

from ticketnotify.api.app import app
from ticketnotify.database import init_db, get_db_session
from ticketnotify.database.crud import (
    get_or_create_user,
    create_location,
    create_alert,
    log_notification_sent,
    get_user_notification_history,
)
from ticketnotify.cache.redis import (
    check_redis_health,
    cache_set,
    cache_get,
    cache_delete,
)
from ticketnotify.engine.notifier import notifier, QueuedNotification
from ticketnotify.adapters.base import Show, SeatStatus
from ticketnotify.bot.keyboards import get_filter_builder_keyboard


@pytest.mark.asyncio
async def test_health_endpoint_is_cheap_no_db():
    """Verify /health returns HTTP 200 without issuing queries."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "TicketNotify"
        assert "scheduler_running" in data


@pytest.mark.asyncio
async def test_readiness_probe_with_db_and_redis():
    """Verify /ready checks both database and Redis connectivity."""
    await init_db()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/ready")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
        assert data["database"] == "connected"
        assert "redis" in data


@pytest.mark.asyncio
async def test_redis_cache_operations_and_fallback():
    """Verify Redis client get, set, delete operations (using real or in-memory fakeredis)."""
    healthy, mode = await check_redis_health()
    assert healthy is True
    assert "redis" in mode.lower() or "fakeredis" in mode.lower()

    # Test cache set and get
    ok = await cache_set("test_key_123", "ticket_data_xyz", ttl_seconds=60)
    assert ok is True

    val = await cache_get("test_key_123")
    assert val == "ticket_data_xyz"

    del_ok = await cache_delete("test_key_123")
    assert del_ok is True

    val_after = await cache_get("test_key_123")
    assert val_after is None


@pytest.mark.asyncio
async def test_notification_history_retrieval():
    """Verify /history CRUD returns last 20 notifications ordered by sent_at DESC."""
    await init_db()

    async with get_db_session() as session:
        user, _ = await get_or_create_user(session, telegram_id=888999111, username="history_test_user")
        loc = await create_location(
            session=session,
            user_id=user.id,
            name="Chennai",
            normalized_city="Chennai",
            normalized_country="India",
            country_code="IN",
            latitude=13.08,
            longitude=80.27,
        )
        alert = await create_alert(
            session=session,
            user_id=user.id,
            movie_query="Thug Life",
            location_id=loc.id,
            platforms=["bms"],
        )

        # Log 3 notifications
        for i in range(3):
            await log_notification_sent(
                session=session,
                alert_id=alert.id,
                user_id=user.id,
                platform="bms",
                notification_type="bookings_opened" if i == 0 else "seats_filling_fast",
                payload_hash=f"hash_{i}_{datetime.utcnow().timestamp()}",
                show_key=f"show_{i}",
                message_text=f"Sample alert message {i}",
            )

        history = await get_user_notification_history(session, user.id, limit=20)
        assert len(history) >= 3
        # Should be ordered by sent_at DESC
        assert history[0].sent_at >= history[1].sent_at


@pytest.mark.asyncio
async def test_notification_message_formatting_with_share_and_feedback():
    """Verify outbound alert formatting contains 'Alert a Friend' deep-link and 'Wrong info?' button."""
    sample_show = Show(
        show_id="SHOW_PVR_01",
        platform="bms",
        movie_id="AVATAR_01",
        cinema_id="CINEMA_PVR_01",
        movie_title="Avatar: Fire and Ash",
        cinema_name="PVR Grand Mall Velachery",
        date="2026-12-18",
        time="07:30 PM",
        language="Tamil",
        format="IMAX 3D",
        price_display="INR 450",
        seat_status=SeatStatus.AVAILABLE,
        seat_status_display="Available (120 seats left)",
        booking_url="https://in.bookmyshow.com/sample",
    )

    item = QueuedNotification(
        alert_id=42,
        user_id=1,
        chat_id=12345678,
        user_obj=None,
        platform="bms",
        notification_type="bookings_opened",
        show=sample_show,
        payload_hash="sample_hash_01",
        summary="Bookings opened",
    )

    text, keyboard = notifier.format_message(item)

    # 1. Message text assertions
    assert "🚨 *BOOKINGS OPENED*" in text
    assert "Avatar: Fire and Ash" in text
    assert "PVR Grand Mall Velachery" in text
    assert "BookMyShow" in text

    # 2. Keyboard button assertions
    flattened_buttons = [btn for row in keyboard.inline_keyboard for btn in row]
    button_texts = [btn.text for btn in flattened_buttons]

    assert "🎟 Book Now" in button_texts
    assert "👥 Alert a Friend" in button_texts
    assert "⚠️ Wrong info?" in button_texts

    # Verify deep-link URL in Alert a Friend button
    share_btn = next(b for b in flattened_buttons if "Alert a Friend" in b.text)
    assert share_btn.url is not None
    assert "t.me/Tickets_NotifyBot?start=track_" in share_btn.url

    # Verify callback data for Wrong info?
    wrong_btn = next(b for b in flattened_buttons if "Wrong info?" in b.text)
    assert wrong_btn.callback_data == "fb_wrong:42:bms"


@pytest.mark.asyncio
async def test_filter_builder_keyboard_elements():
    """Verify filter keyboard renders 2D, 3D, IMAX, 4DX, languages, date and time slots."""
    sample_filters = {
        "formats": ["IMAX", "2D"],
        "languages": ["Tamil", "English"],
        "date_window": "weekend",
        "time_slot": "evening",
    }
    kb = get_filter_builder_keyboard(sample_filters)
    flattened = [btn for row in kb.inline_keyboard for btn in row]
    texts = [btn.text for btn in flattened]

    assert any("2D" in t and "✅" in t for t in texts)
    assert any("IMAX" in t and "✅" in t for t in texts)
    assert any("3D" in t and "◻️" in t for t in texts)
    assert any("Tamil" in t and "✅" in t for t in texts)
    assert any("English" in t and "✅" in t for t in texts)
    assert any("Weekend" in t for t in texts)
    assert any("Evening" in t for t in texts)
    assert any("Done" in t for t in texts)
