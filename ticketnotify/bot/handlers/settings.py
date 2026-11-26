"""User settings and quiet hours handler: /settings."""

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from ticketnotify.bot.states import SettingsFlow
from ticketnotify.bot.keyboards import get_settings_keyboard, get_language_keyboard
from ticketnotify.database.session import get_db_session
from ticketnotify.database.crud import (
    get_or_create_user,
    update_user_quiet_hours,
)

router = Router(name="settings_router")


@router.message(F.text == "⚙️ Settings")
@router.message(F.text == "⚙️ Settings")
@router.message(Command("settings"))
async def handle_settings_command(message: Message):
    async with get_db_session() as session:
        user, _ = await get_or_create_user(session, message.from_user.id)

    await message.answer(
        "⚙️ *Notification & Account Settings*\n\n"
        "Configure quiet hours to avoid night notifications, change language, or manage your data:",
        parse_mode="Markdown",
        reply_markup=get_settings_keyboard(user),
    )


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
