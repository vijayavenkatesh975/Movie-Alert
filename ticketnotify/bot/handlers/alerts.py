"""Alert management handlers: /list, /remove, and inline controls."""

import asyncio
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery

from ticketnotify.database.session import get_db_session
from ticketnotify.database.crud import (
    get_user_by_telegram_id,
    get_user_alerts,
    get_alert_by_id,
    update_alert_status,
    set_alert_mute,
    delete_alert,
)
from ticketnotify.bot.keyboards import get_alert_item_keyboard

router = Router(name="alerts_router")


@router.message(F.text == "🔔 My Alerts")
@router.message(Command("list"))
@router.message(F.text == "🔔 My Alerts")
async def handle_list_alerts(message: Message):
    async with get_db_session() as session:
        user = await get_user_by_telegram_id(session, message.from_user.id)
        if not user:
            await message.answer("You haven't set up any alerts yet. Use /track to get started!")
            return
        alerts = await get_user_alerts(session, user.id)

    if not alerts:
        await message.answer(
            "📋 *You currently have no active alerts.*\n\n"
            "Use /track to set up real-time ticket alerts for any movie worldwide!",
            parse_mode="Markdown",
        )
        return

    await message.answer(f"📋 *Your Active Alerts ({len(alerts)}):*", parse_mode="Markdown")

    platform_names = {
        "bms": "BookMyShow",
        "ticketnew": "Ticketnew",
        "district": "District",
        "pvrinox": "PVR INOX",
    }

    for alert in alerts:
        status_emoji = "🟢 Active" if alert.status == "active" else "⏸ Paused"
        mute_badge = " [🔕 Muted]" if alert.is_muted else ""
        city_name = alert.location.normalized_city if alert.location else "Global"
        platforms = ", ".join([platform_names.get(p, p.upper()) for p in (alert.platforms or [])])
        formats = ", ".join(alert.filters_json.get("formats", [])) or "All formats"

        # Theatres display
        sel_c = getattr(alert, "selected_cinemas", {}) or {}
        num_c = len(sel_c.get("canonical_ids", []))
        theatres_str = f"{num_c} selected" if num_c else "All in radius"

        # Seats display
        s_need = getattr(alert, "seats_needed", 1) or 1
        s_consec = "Consecutive" if getattr(alert, "must_be_consecutive", True) else "Flexible"
        s_cat = (getattr(alert, "seat_category", "any") or "any").title()
        seats_str = f"{s_need} seat(s) ({s_consec}, {s_cat})"

        urgency_str = getattr(alert, "urgency", "WARM")

        text = (
            f"🎬 *{alert.movie_query}* (Alert #{alert.id})\n"
            f"📍 Location: {city_name}\n"
            f"🏛 Theatres: {theatres_str}\n"
            f"🏷 Platforms: {platforms}\n"
            f"🎯 Formats: {formats}\n"
            f"💺 Seats: {seats_str}\n"
            f"⚡ Speed: *{urgency_str}* tier\n"
            f"📊 Status: {status_emoji}{mute_badge}"
        )
        await message.answer(
            text,
            parse_mode="Markdown",
            reply_markup=get_alert_item_keyboard(alert),
        )


@router.message(Command("mystatus"))
async def handle_mystatus_command(message: Message):
    async with get_db_session() as session:
        user = await get_user_by_telegram_id(session, message.from_user.id)
        if not user:
            await message.answer("Please send /start to set up your account first.")
            return
        alerts = await get_user_alerts(session, user.id)
        loc = await get_default_location(session, user.id)

    # 1. City & Theatres
    city = loc.normalized_city if loc else "Chennai"
    user_theatres = (user.selected_theatres or {}).get("canonical_ids", [])
    theatre_names = (user.selected_theatres or {}).get("names", [])
    theatre_count_str = f"{len(user_theatres)} selected" if user_theatres else f"All theatres in {city}"

    chains = getattr(user, "selected_chains", None) or ["PVR", "INOX", "AGS", "Rohini", "Cinepolis"]
    chains_str = ", ".join(chains[:4])

    # 2. Quiet Hours & Snooze
    qh = f"🟢 Active ({user.quiet_hours_start}:00 - {user.quiet_hours_end}:00)" if user.quiet_hours_enabled else "🔴 Disabled"
    if getattr(user, "snoozed_until", None) and user.snoozed_until > datetime.utcnow():
        snooze_str = f"💤 Snoozed until {user.snoozed_until.strftime('%H:%M UTC')}"
    elif getattr(user, "alerts_paused", False):
        snooze_str = "⏸ All Alerts Paused"
    else:
        snooze_str = "🟢 Alerts Active"

    # 3. Notification triggers
    prefs = getattr(user, "notification_preferences", None) or {}
    active_triggers = [k.replace("_", " ").title() for k, v in prefs.items() if v is True]
    if not active_triggers:
        active_triggers = ["Bookings Opened", "New Shows", "Price Drops", "Preferred Seats"]

    # 4. Platform Health
    from ticketnotify.adapters.registry import registry
    cb_statuses = registry.get_circuit_statuses()
    plat_health = []
    for cb in cb_statuses:
        p_name = cb["platform"].upper()
        p_state = cb["state"]
        if p_state == "closed":
            plat_health.append(f"• {p_name}: 🟢 Live & Scanning")
        else:
            plat_health.append(f"• {p_name}: 🟡 Cooldown Probe ({cb.get('failure_count', 0)} fails)")

    # 5. Tracked Movies
    lines = [
        "📊 *Your TicketNotify Dashboard & Account Status*\n",
        f"📍 *Selected City:* {city}",
        f"🏛 *Theatres Monitored:* {theatre_count_str}",
        f"🏢 *Preferred Chains:* {chains_str}",
        f"🌙 *Quiet Hours:* {qh}",
        f"🔔 *Watch Status:* {snooze_str}",
        f"🎯 *Active Triggers:* {', '.join(active_triggers[:4])}\n",
        "*📡 Platform Health:*",
        "\n".join(plat_health),
        "",
    ]

    if alerts:
        lines.append(f"*🎬 Active Movie Watches ({len(alerts)}):*")
        for a in alerts:
            speed = getattr(a, "urgency", "WARM")
            emoji = "🔥" if speed == "HOT" else "⚡"
            lines.append(f"• *{a.movie_query}* (Alert #{a.id}) | {emoji} {speed} speed tier | Status: {a.status.title()}")
            sel_cin = a.selected_cinemas or {}
            c_names = sel_cin.get("names", [])
            if c_names:
                lines.append(f"  🏛 Theatres: {', '.join(c_names[:3])}{'...' if len(c_names) > 3 else ''}")
    else:
        lines.append("ℹ️ _No active movie watches. Tap '🎬 Now Showing' or send /track to start!_")

    await message.answer("\n".join(lines), parse_mode="Markdown")


@router.message(Command("test"))
async def handle_test_command(message: Message):
    """Sends sample real-time alerts demonstrating each platform's notification layout."""
    await message.answer("🧪 *Generating sample notifications across all 4 platforms...*", parse_mode="Markdown")

    from ticketnotify.adapters.base import Show, SeatStatus
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    samples = [
        (
            "BookMyShow",
            "🚨 *BOOKINGS OPENED*\n\n"
            "🎬 *Avatar: Fire and Ash* (English, IMAX 3D)\n"
            "📍 PVR IMAX: Forum Mall, Koramangala\n"
            "🕒 2026-12-18 | 10:30 AM\n"
            "💺 🟡 Filling Fast (45 seats left) | INR 450 - 850\n"
            "🎯 *Recommended:* Row F (F12, F13, F14) - Center / Recliner - ₹650/seat (Score: 124.5)\n"
            "🏷 Platform: *BookMyShow*",
            "https://in.bookmyshow.com",
        ),
        (
            "PVR INOX",
            "✨ *NEW SHOW ADDED*\n\n"
            "🎬 *Avatar: Fire and Ash* (English, P[XL])\n"
            "📍 PVR: Vega City, Bannerghatta Road\n"
            "🕒 2026-12-18 | 07:15 PM\n"
            "💺 🟢 Available (180 seats left) | From INR 320\n"
            "🎯 *Recommended:* Row G (G10, G11) - Center / Prime - ₹420/seat (Score: 118.0)\n"
            "🏷 Platform: *PVR INOX*",
            "https://www.pvrcinemas.com",
        ),
        (
            "District (Zomato)",
            "⚡ *SEATS FILLING FAST*\n\n"
            "🎬 *Avatar: Fire and Ash* (Tamil, 3D)\n"
            "📍 Cinepolis: Orion East Mall, Banaswadi\n"
            "🕒 2026-12-18 | 04:00 PM\n"
            "💺 🟠 Almost Full (12 seats left) | INR 250\n"
            "🏷 Platform: *District (by Zomato)*",
            "https://www.district.in",
        ),
        (
            "Ticketnew",
            "📉 *PRICE DROP*\n\n"
            "🎬 *Avatar: Fire and Ash* (Hindi, 2D)\n"
            "📍 INOX: Garuda Mall, Magrath Road\n"
            "🕒 2026-12-18 | 01:30 PM\n"
            "💺 🟢 Available | Price dropped from ₹280 to ₹180\n"
            "🏷 Platform: *Ticketnew*",
            "https://ticketnew.com",
        ),
    ]

    for plat_name, text, url in samples:
        buttons = [
            [InlineKeyboardButton(text=f"🎟 Book on {plat_name}", url=url)],
            [
                InlineKeyboardButton(text="🔕 Mute Alert", callback_data="test_mute"),
                InlineKeyboardButton(text="🛑 Stop Tracking", callback_data="test_stop"),
            ],
        ]
        await message.answer(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        await asyncio.sleep(0.3)


@router.message(Command("remove"))
async def handle_remove_command(message: Message):
    args = message.text.split()
    if len(args) < 2:
        await message.answer(
            "To remove an alert, view your alerts with /list and tap *Delete Alert*, "
            "or use `/remove <alert_id>`.",
            parse_mode="Markdown",
        )
        return

    try:
        alert_id = int(args[1])
        async with get_db_session() as session:
            await delete_alert(session, alert_id)
        await message.answer(f"✅ Alert #{alert_id} deleted successfully.")
    except Exception as e:
        await message.answer(f"Error removing alert: {e}")


@router.callback_query(F.data.startswith("pause_alert:"))
async def on_pause_alert(query: CallbackQuery):
    alert_id = int(query.data.split(":")[1])
    async with get_db_session() as session:
        await update_alert_status(session, alert_id, "paused")
        alert = await get_alert_by_id(session, alert_id)

    if alert:
        await query.message.edit_reply_markup(reply_markup=get_alert_item_keyboard(alert))
    await query.answer("Alert paused. You will not receive notifications until resumed.")


@router.callback_query(F.data.startswith("resume_alert:"))
async def on_resume_alert(query: CallbackQuery):
    alert_id = int(query.data.split(":")[1])
    async with get_db_session() as session:
        await update_alert_status(session, alert_id, "active")
        alert = await get_alert_by_id(session, alert_id)

    if alert:
        await query.message.edit_reply_markup(reply_markup=get_alert_item_keyboard(alert))
    await query.answer("Alert resumed! Monitoring is active.")


@router.callback_query(F.data.startswith("mute:"))
async def on_mute_alert(query: CallbackQuery):
    alert_id = int(query.data.split(":")[1])
    async with get_db_session() as session:
        await set_alert_mute(session, alert_id, True)
        alert = await get_alert_by_id(session, alert_id)

    if alert:
        try:
            await query.message.edit_reply_markup(reply_markup=get_alert_item_keyboard(alert))
        except Exception:
            pass
    await query.answer("Alert muted.")


@router.callback_query(F.data.startswith("unmute:"))
async def on_unmute_alert(query: CallbackQuery):
    alert_id = int(query.data.split(":")[1])
    async with get_db_session() as session:
        await set_alert_mute(session, alert_id, False)
        alert = await get_alert_by_id(session, alert_id)

    if alert:
        await query.message.edit_reply_markup(reply_markup=get_alert_item_keyboard(alert))
    await query.answer("Alert unmuted. Notifications enabled.")


@router.callback_query(F.data.startswith("delete_alert:") | F.data.startswith("stop:"))
async def on_delete_alert(query: CallbackQuery):
    alert_id = int(query.data.split(":")[1])
    async with get_db_session() as session:
        await delete_alert(session, alert_id)

    await query.message.edit_text("🗑 *Alert deleted and monitoring stopped.*", parse_mode="Markdown")
    await query.answer("Alert removed.")
