"""Handlers for movie discovery: Now Showing, Coming Soon, and quick tracking."""

import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from ticketnotify.database.session import get_db_session
from ticketnotify.database.crud import get_or_create_user, get_default_location
from ticketnotify.engine.discovery import get_coming_soon_movies, get_now_showing_movies
from ticketnotify.bot.keyboards import get_discovery_card_keyboard
from ticketnotify.bot.handlers.track import TrackFlow, search_and_present_matches
from ticketnotify.location.matcher import map_location_to_platforms

logger = logging.getLogger(__name__)
router = Router(name="discovery_router")


@router.message(F.text == "🗓 Coming Soon")
@router.message(Command("comingsoon"))
async def handle_coming_soon(message: Message):
    async with get_db_session() as session:
        user, _ = await get_or_create_user(session, message.from_user.id)
        default_loc = await get_default_location(session, user.id)

    city = default_loc.normalized_city if default_loc else "Bengaluru"
    country = default_loc.country_code if default_loc else "in"
    movies = get_coming_soon_movies(city=city, country=country)

    await message.answer(
        f"🗓 *Upcoming Movies for {city}*\n"
        "Here are the major upcoming releases. Tap *'Alert when bookings open'* to get an instant notification:",
        parse_mode="Markdown",
    )

    for m in movies[:5]:
        langs = ", ".join(m["languages"])
        fmts = ", ".join(m["formats"])
        card_text = (
            f"🎬 *{m['title']}*\n"
            f"⏳ *{m['countdown']}*\n"
            f"🗣 Languages: {langs}\n"
            f"🎞 Formats: {fmts}\n"
            f"📖 {m.get('synopsis', '')}"
        )
        await message.answer(
            card_text,
            parse_mode="Markdown",
            reply_markup=get_discovery_card_keyboard(m["title"], is_now_showing=False),
        )


@router.message(F.text == "🎬 Now Showing")
@router.message(Command("nowshowing"))
async def handle_now_showing(message: Message):
    async with get_db_session() as session:
        user, _ = await get_or_create_user(session, message.from_user.id)
        default_loc = await get_default_location(session, user.id)

    city = default_loc.normalized_city if default_loc else "Bengaluru"
    country = default_loc.country_code if default_loc else "in"
    movies = get_now_showing_movies(city=city, country=country)

    await message.answer(
        f"🎬 *Now Showing in {city}*\n"
        "Movies currently running in theatres. Tap *'Track current shows'* to monitor seats and price drops:",
        parse_mode="Markdown",
    )

    for m in movies:
        langs = ", ".join(m["languages"])
        fmts = ", ".join(m["formats"])
        card_text = (
            f"🎬 *{m['title']}*\n"
            f"📅 Released: {m['release_date']}\n"
            f"🗣 Languages: {langs}\n"
            f"🎞 Formats: {fmts}\n"
            f"📖 {m.get('synopsis', '')}"
        )
        await message.answer(
            card_text,
            parse_mode="Markdown",
            reply_markup=get_discovery_card_keyboard(m["title"], is_now_showing=True),
        )


@router.callback_query(F.data.startswith("disc_open:"))
@router.callback_query(F.data.startswith("disc_track:"))
async def on_discovery_alert_tap(query: CallbackQuery, state: FSMContext):
    movie_title = query.data.split(":", 1)[1]
    await state.clear()
    await state.update_data(movie_query=movie_title)

    # Check user location
    async with get_db_session() as session:
        user, _ = await get_or_create_user(session, query.from_user.id)
        default_loc = await get_default_location(session, user.id)

    if default_loc:
        from ticketnotify.location.models import NormalizedLocation
        norm_loc = NormalizedLocation(
            raw_query=default_loc.name,
            city=default_loc.normalized_city,
            country=default_loc.normalized_country,
            country_code=default_loc.country_code,
            latitude=default_loc.latitude,
            longitude=default_loc.longitude,
            display_name=f"{default_loc.normalized_city}, {default_loc.normalized_country}",
            platform_codes=default_loc.platform_mappings or {},
        )
        norm_loc = map_location_to_platforms(norm_loc)
        await state.update_data(
            location_id=default_loc.id,
            location_obj=norm_loc.dict(),
        )
        await query.message.answer(
            f"🎯 Setting up alert for *'{movie_title}'* in *{default_loc.normalized_city}*...",
            parse_mode="Markdown",
        )
        await search_and_present_matches(query.message, state, movie_title, norm_loc)
    else:
        from ticketnotify.bot.keyboards import get_location_request_keyboard
        await query.message.answer(
            f"📍 What is your city for *'{movie_title}'*?\n\n"
            "Please share your location or type your city name:",
            parse_mode="Markdown",
            reply_markup=get_location_request_keyboard(),
        )
        await state.set_state(TrackFlow.waiting_for_location)

    await query.answer()


@router.callback_query(F.data.startswith("disc_info:"))
async def on_discovery_info_tap(query: CallbackQuery):
    title = query.data.split(":", 1)[1]
    await query.answer(f"Selected: {title}. Tap 'Alert when bookings open' to track!", show_alert=True)
