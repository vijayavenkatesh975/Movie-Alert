"""Location management handlers: /location."""

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, ReplyKeyboardRemove

from ticketnotify.bot.states import LocationFlow
from ticketnotify.bot.keyboards import get_location_request_keyboard
from ticketnotify.database.session import get_db_session
from ticketnotify.database.crud import (
    get_or_create_user,
    get_default_location,
    create_location,
)
from ticketnotify.location import geocoder

router = Router(name="location_router")


@router.message(Command("location"))
async def handle_location_command(message: Message, state: FSMContext):
    async with get_db_session() as session:
        user, _ = await get_or_create_user(session, message.from_user.id)
        current_loc = await get_default_location(session, user.id)

    curr_str = f"*{current_loc.name}*" if current_loc else "_None set_"

    await message.answer(
        f"📍 *Default Location Management*\n\n"
        f"Current default location: {curr_str}\n\n"
        "To update your location, please send:\n"
        "• City name (e.g. `Bengaluru`, `Mumbai`, `New York`, `London`)\n"
        "• Pincode or Area (e.g. `560034`, `10001`)\n"
        "• Or share your GPS location with the button below:",
        parse_mode="Markdown",
        reply_markup=get_location_request_keyboard(),
    )
    await state.set_state(LocationFlow.waiting_for_location)


@router.message(LocationFlow.waiting_for_location, F.location)
async def update_location_gps(message: Message, state: FSMContext):
    lat = message.location.latitude
    lng = message.location.longitude

    wait_msg = await message.answer("🔍 Resolving GPS location...", reply_markup=ReplyKeyboardRemove())
    norm = await geocoder.reverse_geocode(lat, lng)

    if not norm:
        await wait_msg.edit_text("Could not resolve location. Please type your city name:")
        return

    async with get_db_session() as session:
        user, _ = await get_or_create_user(session, message.from_user.id)
        loc = await create_location(
            session=session,
            user_id=user.id,
            name=norm.label,
            normalized_city=norm.city,
            normalized_country=norm.country,
            country_code=norm.country_code,
            latitude=norm.latitude,
            longitude=norm.longitude,
            platform_mappings=norm.platform_codes,
            is_default=True,
        )

    await state.clear()
    await wait_msg.edit_text(
        f"✅ *Default location updated to:* {norm.label}\n\n"
        f"Available booking platforms: {', '.join(norm.supported_platforms).upper()}",
        parse_mode="Markdown",
    )


@router.message(LocationFlow.waiting_for_location, F.text)
async def update_location_text(message: Message, state: FSMContext):
    if message.text == "❌ Cancel":
        await state.clear()
        await message.answer("Location update cancelled.", reply_markup=ReplyKeyboardRemove())
        return

    query_text = message.text.strip()
    wait_msg = await message.answer(f"🔍 Geocoding '{query_text}'...", reply_markup=ReplyKeyboardRemove())
    norm = await geocoder.geocode(query_text)

    if not norm:
        await wait_msg.edit_text(f"Could not find '{query_text}'. Please try another city:")
        return

    async with get_db_session() as session:
        user, _ = await get_or_create_user(session, message.from_user.id)
        loc = await create_location(
            session=session,
            user_id=user.id,
            name=norm.label,
            normalized_city=norm.city,
            normalized_country=norm.country,
            country_code=norm.country_code,
            latitude=norm.latitude,
            longitude=norm.longitude,
            platform_mappings=norm.platform_codes,
            is_default=True,
        )

    await state.clear()
    await wait_msg.edit_text(
        f"✅ *Default location updated to:* {norm.label}\n\n"
        f"Available booking platforms: {', '.join(norm.supported_platforms).upper()}",
        parse_mode="Markdown",
    )
