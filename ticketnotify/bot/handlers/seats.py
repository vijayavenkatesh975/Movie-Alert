"""Handler for /seats command to configure seat preferences on active alerts."""

import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from ticketnotify.database.session import get_db_session
from ticketnotify.database.crud import (
    get_user_by_telegram_id,
    get_user_alerts,
    get_alert_by_id,
    update_alert_seat_prefs,
)
from ticketnotify.bot.keyboards import get_seat_preferences_keyboard
from ticketnotify.bot.states import SeatsFlow

logger = logging.getLogger(__name__)
router = Router(name="seats_router")


@router.message(F.text == "💺 Seat Preferences")
@router.message(Command("seats"))
async def handle_seats_command(message: Message, state: FSMContext):
    await state.clear()
    async with get_db_session() as session:
        user = await get_user_by_telegram_id(session, message.from_user.id)
        if not user:
            await message.answer("You don't have any active alerts yet. Use /track to get started!")
            return
        alerts = await get_user_alerts(session, user.id)

    if not alerts:
        await message.answer("You have no active alerts to configure seat preferences for.")
        return

    buttons = []
    for a in alerts:
        city = a.location.normalized_city if a.location else "Global"
        buttons.append([
            InlineKeyboardButton(
                text=f"🎬 {a.movie_query} ({city})",
                callback_data=f"sel_alert_seats:{a.id}",
            )
        ])
    buttons.append([InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_flow")])

    await message.answer(
        "💺 *Select an alert to configure seat preferences:*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await state.set_state(SeatsFlow.choosing_alert)


@router.callback_query(SeatsFlow.choosing_alert, F.data.startswith("sel_alert_seats:"))
@router.callback_query(F.data.startswith("edit_seats:"))
async def on_alert_chosen_for_seats(query: CallbackQuery, state: FSMContext):
    alert_id = int(query.data.split(":")[1])
    async with get_db_session() as session:
        alert = await get_alert_by_id(session, alert_id)

    if not alert:
        await query.answer("Alert not found.", show_alert=True)
        return

    prefs = {
        "seats_needed": getattr(alert, "seats_needed", 1) or 1,
        "must_be_consecutive": getattr(alert, "must_be_consecutive", True),
        "row_zone": getattr(alert, "row_zone", "any") or "any",
        "column_zone": getattr(alert, "column_zone", "any") or "any",
        "seat_category": getattr(alert, "seat_category", "any") or "any",
    }

    await state.update_data(edit_alert_id=alert_id, seat_prefs=prefs)
    await query.message.edit_text(
        f"💺 *Seat Preferences for {alert.movie_query}*\n\n"
        "Configure group size, consecutive requirement, screen row/column zone, and category:",
        parse_mode="Markdown",
        reply_markup=get_seat_preferences_keyboard(prefs),
    )
    await state.set_state(SeatsFlow.configuring_seats)
    await query.answer()


@router.callback_query(SeatsFlow.configuring_seats, F.data == "seat_cycle_needed")
async def on_cycle_needed(query: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    prefs = data.get("seat_prefs", {})
    needed = prefs.get("seats_needed", 1)
    prefs["seats_needed"] = (needed % 10) + 1
    await state.update_data(seat_prefs=prefs)
    await query.message.edit_reply_markup(reply_markup=get_seat_preferences_keyboard(prefs))
    await query.answer()


@router.callback_query(SeatsFlow.configuring_seats, F.data == "seat_toggle_consec")
async def on_toggle_consec(query: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    prefs = data.get("seat_prefs", {})
    prefs["must_be_consecutive"] = not prefs.get("must_be_consecutive", True)
    await state.update_data(seat_prefs=prefs)
    await query.message.edit_reply_markup(reply_markup=get_seat_preferences_keyboard(prefs))
    await query.answer()


@router.callback_query(SeatsFlow.configuring_seats, F.data == "seat_cycle_row")
async def on_cycle_row(query: CallbackQuery, state: FSMContext):
    zones = ["any", "front", "middle", "back"]
    data = await state.get_data()
    prefs = data.get("seat_prefs", {})
    curr = prefs.get("row_zone", "any")
    next_idx = (zones.index(curr) + 1) % len(zones) if curr in zones else 0
    prefs["row_zone"] = zones[next_idx]
    await state.update_data(seat_prefs=prefs)
    await query.message.edit_reply_markup(reply_markup=get_seat_preferences_keyboard(prefs))
    await query.answer()


@router.callback_query(SeatsFlow.configuring_seats, F.data == "seat_cycle_col")
async def on_cycle_col(query: CallbackQuery, state: FSMContext):
    zones = ["any", "center", "left", "right", "aisle"]
    data = await state.get_data()
    prefs = data.get("seat_prefs", {})
    curr = prefs.get("column_zone", "any")
    next_idx = (zones.index(curr) + 1) % len(zones) if curr in zones else 0
    prefs["column_zone"] = zones[next_idx]
    await state.update_data(seat_prefs=prefs)
    await query.message.edit_reply_markup(reply_markup=get_seat_preferences_keyboard(prefs))
    await query.answer()


@router.callback_query(SeatsFlow.configuring_seats, F.data == "seat_cycle_cat")
async def on_cycle_cat(query: CallbackQuery, state: FSMContext):
    cats = ["any", "Recliner", "Premium", "Gold", "Silver"]
    data = await state.get_data()
    prefs = data.get("seat_prefs", {})
    curr = prefs.get("seat_category", "any")
    next_idx = (cats.index(curr) + 1) % len(cats) if curr in cats else 0
    prefs["seat_category"] = cats[next_idx]
    await state.update_data(seat_prefs=prefs)
    await query.message.edit_reply_markup(reply_markup=get_seat_preferences_keyboard(prefs))
    await query.answer()


@router.callback_query(SeatsFlow.configuring_seats, F.data == "seat_prefs_done")
async def on_seat_prefs_save(query: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    prefs = data.get("seat_prefs", {})
    alert_id = data.get("edit_alert_id")

    async with get_db_session() as session:
        await update_alert_seat_prefs(
            session=session,
            alert_id=alert_id,
            seats_needed=prefs.get("seats_needed", 1),
            must_be_consecutive=prefs.get("must_be_consecutive", True),
            row_zone=prefs.get("row_zone", "any"),
            column_zone=prefs.get("column_zone", "any"),
            seat_category=prefs.get("seat_category", "any"),
        )

    await query.message.edit_text(
        f"✅ Saved seat preferences!\n"
        f"💺 Seats: {prefs.get('seats_needed')} | Consecutive: {prefs.get('must_be_consecutive')}\n"
        f"↕️ Row: {prefs.get('row_zone').title()} | ↔️ Col: {prefs.get('column_zone').title()}\n"
        f"🏷 Category: {prefs.get('seat_category')}"
    )
    await state.clear()
    await query.answer()
