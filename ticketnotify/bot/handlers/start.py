"""/start and first-time guided onboarding flow."""

from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove
from sqlalchemy import update

from ticketnotify.database.session import get_db_session
from ticketnotify.database.crud import (
    get_or_create_user,
    update_user_language,
    create_location,
    get_default_location,
)
from ticketnotify.database.models import User
from ticketnotify.bot.keyboards import (
    get_language_keyboard,
    get_location_request_keyboard,
    get_main_menu_keyboard,
)
from ticketnotify.bot.states import StartFlow
from ticketnotify.location import geocoder, map_location_to_platforms

router = Router(name="start_router")


@router.message(CommandStart())
async def handle_start(message: Message, state: FSMContext):
    await state.clear()
    async with get_db_session() as session:
        user, created = await get_or_create_user(
            session=session,
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
        )
        # Reactivate user if previously marked inactive
        if not user.is_active:
            await session.execute(
                update(User).where(User.id == user.id).values(is_active=True)
            )

    welcome_text = (
        f"👋 *Welcome to TicketNotify, {message.from_user.first_name or 'Movie Buff'}!*\n\n"
        "This is an *instant alert bot* for cinema tickets. We monitor ticket counters "
        "and alert you the split second bookings open or your preferred seats appear, "
        "with direct booking links so you can book yourself.\n\n"
        "🌐 *Step 1 of 2: Please select your language:*"
    )

    await message.answer(
        welcome_text,
        parse_mode="Markdown",
        reply_markup=get_language_keyboard(),
    )


@router.callback_query(F.data.startswith("lang:"))
async def handle_lang_callback(query: CallbackQuery, state: FSMContext):
    lang_code = query.data.split(":")[1]
    async with get_db_session() as session:
        user, _ = await get_or_create_user(
            session=session,
            telegram_id=query.from_user.id,
        )
        await update_user_language(session, user.id, lang_code)

    lang_names = {
        "en": "English",
        "ta": "தமிழ் (Tamil)",
        "hi": "हिन्दी (Hindi)",
        "te": "తెలుగు (Telugu)",
    }

    await query.message.edit_text(
        f"✅ Language set to *{lang_names.get(lang_code, 'English')}*!",
        parse_mode="Markdown",
    )

    # Prompt for Location
    loc_prompt = (
        "📍 *Step 2 of 2: Where do you watch movies?*\n\n"
        "Tell us your location (works worldwide):\n"
        "• Tap *'Share Current Location'* below\n"
        "• Or type your city/area/pincode (e.g. `Chennai`, `Bengaluru`, `Mumbai`, `London`):"
    )
    await query.message.answer(
        loc_prompt,
        parse_mode="Markdown",
        reply_markup=get_location_request_keyboard(),
    )
    await state.set_state(StartFlow.waiting_for_location)
    await query.answer()


@router.message(StartFlow.waiting_for_location, F.location)
async def process_start_location_gps(message: Message, state: FSMContext):
    lat = message.location.latitude
    lng = message.location.longitude

    wait_msg = await message.answer("🔍 Resolving GPS coordinates...", reply_markup=ReplyKeyboardRemove())
    norm_loc = await geocoder.reverse_geocode(lat, lng)

    if not norm_loc:
        await wait_msg.edit_text("Could not resolve location. Please type your city name manually:")
        return

    await finish_onboarding_location(message, state, norm_loc, wait_msg)


@router.message(StartFlow.waiting_for_location, F.text)
async def process_start_location_text(message: Message, state: FSMContext):
    if message.text == "❌ Cancel":
        await state.clear()
        await message.answer("Location setup skipped. You can configure it later with /location.", reply_markup=get_main_menu_keyboard())
        return

    query_text = message.text.strip()
    wait_msg = await message.answer(f"🔍 Finding '{query_text}'...", reply_markup=ReplyKeyboardRemove())
    norm_loc = await geocoder.geocode(query_text)

    if not norm_loc:
        await wait_msg.edit_text(f"❌ Could not find '{query_text}'. Please try another city or area name:")
        return

    await finish_onboarding_location(message, state, norm_loc, wait_msg)


async def finish_onboarding_location(message: Message, state: FSMContext, norm_loc, wait_msg: Message):
    async with get_db_session() as session:
        user, _ = await get_or_create_user(session, message.from_user.id)
        loc = await create_location(
            session=session,
            user_id=user.id,
            name=norm_loc.label,
            normalized_city=norm_loc.city,
            normalized_country=norm_loc.country,
            country_code=norm_loc.country_code,
            latitude=norm_loc.latitude,
            longitude=norm_loc.longitude,
            platform_mappings=norm_loc.platform_codes,
            is_default=True,
        )

    await state.clear()

    # Build platform compatibility breakdown
    platform_labels = {
        "bms": "BookMyShow",
        "pvrinox": "PVR INOX",
        "district": "District (by Zomato)",
        "ticketnew": "Ticketnew",
    }
    lines = [f"📍 *Location Confirmed:* {norm_loc.city}, {norm_loc.country}\n"]
    lines.append("*Booking Platforms in your region:*")

    for p in ["bms", "pvrinox", "district", "ticketnew"]:
        if p in norm_loc.supported_platforms:
            lines.append(f"• {platform_labels.get(p, p.upper())}: 🟢 Available")
        else:
            lines.append(f"• {platform_labels.get(p, p.upper())}: 🔴 Not available in {norm_loc.country}")

    lines.append(
        "\n🎉 *Setup Complete!* Default theatres set to all within 10 km.\n"
        "Use the menu buttons below to browse movies or configure alerts:"
    )

    await wait_msg.delete()
    await message.answer(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=get_main_menu_keyboard(),
    )
