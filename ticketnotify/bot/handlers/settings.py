"""User settings, notification preferences, quiet hours, and snooze: /settings."""

from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from ticketnotify.bot.states import SettingsFlow
from ticketnotify.bot.keyboards import (
    get_settings_keyboard,
    get_language_keyboard,
    get_notification_settings_keyboard,
    get_snooze_keyboard,
)
from ticketnotify.database.session import get_db_session
from ticketnotify.database.crud import (
    get_or_create_user,
    update_user_quiet_hours,
    update_user_notification_preferences,
    set_user_alerts_paused,
    set_user_snooze,
)

router = Router(name="settings_router")


@router.message(F.text == "⚙️ Settings")
@router.message(Command("settings"))
async def handle_settings_command(message: Message):
    async with get_db_session() as session:
        user, _ = await get_or_create_user(session, message.from_user.id)

    await message.answer(
        "⚙️ *Notification & Account Settings*\n\n"
        "Configure individual alert triggers, pause/resume tracking, snooze notifications, or adjust quiet hours:",
        parse_mode="Markdown",
        reply_markup=get_settings_keyboard(user),
    )


@router.message(Command("pause"))
async def handle_pause_command(message: Message):
    async with get_db_session() as session:
        user, _ = await get_or_create_user(session, message.from_user.id)
        await set_user_alerts_paused(session, user.id, paused=True)

    await message.answer(
        "⏸ *All ticket alerts have been paused.*\n"
        "You will not receive any notifications until you send /resume.",
        parse_mode="Markdown",
    )


@router.message(Command("resume"))
async def handle_resume_command(message: Message):
    async with get_db_session() as session:
        user, _ = await get_or_create_user(session, message.from_user.id)
        await set_user_alerts_paused(session, user.id, paused=False)

    await message.answer(
        "▶️ *Alert tracking resumed!* You are actively receiving ticket drop notifications.",
        parse_mode="Markdown",
    )


@router.message(Command("snooze"))
async def handle_snooze_command(message: Message):
    await message.answer(
        "💤 *Snooze Notifications*\nChoose how long to pause alerts:",
        parse_mode="Markdown",
        reply_markup=get_snooze_keyboard(),
    )


@router.callback_query(F.data == "manage_notif_prefs")
async def on_manage_notif_prefs(query: CallbackQuery):
    async with get_db_session() as session:
        user, _ = await get_or_create_user(session, query.from_user.id)
        prefs = user.notification_preferences or {}

    await query.message.edit_text(
        "🔔 *Customise Notification Triggers*\n\n"
        "Tap any trigger to enable or disable notifications for that category:",
        parse_mode="Markdown",
        reply_markup=get_notification_settings_keyboard(prefs),
    )
    await query.answer()


@router.callback_query(F.data.startswith("tog_notif:"))
async def on_toggle_notification_type(query: CallbackQuery):
    key = query.data.split(":")[1]
    async with get_db_session() as session:
        user, _ = await get_or_create_user(session, query.from_user.id)
        prefs = dict(user.notification_preferences or {})
        current_state = prefs.get(key, True)
        new_state = not current_state
        prefs[key] = new_state
        await update_user_notification_preferences(session, user.id, prefs)

    await query.message.edit_reply_markup(reply_markup=get_notification_settings_keyboard(prefs))
    label = "enabled" if new_state else "disabled"
    await query.answer(f"Trigger {key} {label}.")


@router.callback_query(F.data == "pause_all_alerts")
async def on_pause_all_alerts(query: CallbackQuery):
    async with get_db_session() as session:
        user, _ = await get_or_create_user(session, query.from_user.id)
        await set_user_alerts_paused(session, user.id, paused=True)
        user.alerts_paused = True

    await query.message.edit_reply_markup(reply_markup=get_settings_keyboard(user))
    await query.answer("⏸ All alerts paused.")


@router.callback_query(F.data == "resume_all_alerts")
async def on_resume_all_alerts(query: CallbackQuery):
    async with get_db_session() as session:
        user, _ = await get_or_create_user(session, query.from_user.id)
        await set_user_alerts_paused(session, user.id, paused=False)
        user.alerts_paused = False

    await query.message.edit_reply_markup(reply_markup=get_settings_keyboard(user))
    await query.answer("▶️ Alerts resumed.")


@router.callback_query(F.data == "manage_snooze")
async def on_manage_snooze(query: CallbackQuery):
    await query.message.edit_text(
        "💤 *Snooze Notifications*\nSelect duration to temporarily silence alerts:",
        parse_mode="Markdown",
        reply_markup=get_snooze_keyboard(),
    )
    await query.answer()


@router.callback_query(F.data.startswith("set_snooze:"))
async def on_set_snooze_duration(query: CallbackQuery):
    hours = int(query.data.split(":")[1])
    snooze_until = None
    if hours > 0:
        snooze_until = datetime.utcnow() + timedelta(hours=hours)

    async with get_db_session() as session:
        user, _ = await get_or_create_user(session, query.from_user.id)
        await set_user_snooze(session, user.id, snooze_until)
        user.snoozed_until = snooze_until

    await query.message.edit_text(
        f"💤 Alerts snoozed for *{hours} hours*." if hours > 0 else "🔔 Snooze turned off. Alerts are active!",
        parse_mode="Markdown",
        reply_markup=get_settings_keyboard(user),
    )
    await query.answer()


@router.callback_query(F.data == "back_to_settings")
async def on_back_to_settings(query: CallbackQuery):
    async with get_db_session() as session:
        user, _ = await get_or_create_user(session, query.from_user.id)

    await query.message.edit_text(
        "⚙️ *Notification & Account Settings*\n\n"
        "Configure individual alert triggers, pause/resume tracking, snooze notifications, or adjust quiet hours:",
        parse_mode="Markdown",
        reply_markup=get_settings_keyboard(user),
    )
    await query.answer()


@router.callback_query(F.data == "toggle_quiet_hours")
async def toggle_quiet_hours(query: CallbackQuery):
    async with get_db_session() as session:
        user, _ = await get_or_create_user(session, query.from_user.id)
        new_state = not user.quiet_hours_enabled
        await update_user_quiet_hours(
            session=session,
            user_id=user.id,
            enabled=new_state,
            start_hour=user.quiet_hours_start,
            end_hour=user.quiet_hours_end,
        )
        user.quiet_hours_enabled = new_state

    await query.message.edit_reply_markup(reply_markup=get_settings_keyboard(user))
    status_str = "enabled" if new_state else "disabled"
    await query.answer(f"Quiet hours {status_str}.")


@router.callback_query(F.data == "config_quiet_time")
async def prompt_quiet_time(query: CallbackQuery, state: FSMContext):
    await query.message.answer(
        "⏰ *Set Quiet Hours (24-hour format)*\n\n"
        "Please reply with the start and end hours separated by space (e.g. `23 7` for 11 PM to 7 AM):",
        parse_mode="Markdown",
    )
    await state.set_state(SettingsFlow.setting_quiet_hours)
    await query.answer()


@router.message(SettingsFlow.setting_quiet_hours)
async def process_quiet_time_input(message: Message, state: FSMContext):
    parts = message.text.strip().split()
    if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
        await message.answer("Please provide two numbers between 0 and 23 (e.g. `23 7`).")
        return

    start_h = int(parts[0])
    end_h = int(parts[1])
    if not (0 <= start_h <= 23 and 0 <= end_h <= 23):
        await message.answer("Hours must be between 0 and 23.")
        return

    async with get_db_session() as session:
        user, _ = await get_or_create_user(session, message.from_user.id)
        await update_user_quiet_hours(
            session=session,
            user_id=user.id,
            enabled=True,
            start_hour=start_h,
            end_hour=end_h,
        )

    await state.clear()
    await message.answer(f"✅ Quiet hours set to *{start_h}:00 to {end_h}:00*.", parse_mode="Markdown")


@router.callback_query(F.data == "change_language")
async def on_change_language_clicked(query: CallbackQuery):
    await query.message.edit_text(
        "🌐 Choose your preferred language:",
        reply_markup=get_language_keyboard(),
    )
    await query.answer()
