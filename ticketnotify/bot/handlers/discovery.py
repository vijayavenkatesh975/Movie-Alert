"""Handlers for interactive movie discovery with 6 categories, exact release dates, and pagination."""

import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from ticketnotify.database.session import get_db_session
from ticketnotify.database.crud import get_or_create_user, get_default_location
from ticketnotify.engine.discovery import (
    get_movie_catalog_by_category,
    paginate_movies,
    format_movie_card,
)
from ticketnotify.bot.keyboards import get_discovery_catalog_keyboard, get_location_request_keyboard
from ticketnotify.bot.states import TrackFlow, DiscoveryFlow
from ticketnotify.bot.handlers.track import search_and_present_matches
from ticketnotify.location.matcher import map_location_to_platforms

logger = logging.getLogger(__name__)
router = Router(name="discovery_router")

CATEGORY_TITLES = {
    "now_showing": "🎬 Now Showing in Theatres",
    "coming_soon": "🗓 Upcoming Blockbusters & Coming Soon",
    "this_week": "⚡ Releasing This Week",
    "this_month": "📅 Releasing This Month",
    "recent": "🎞 Recently Released",
    "search": "🔍 Movie Search Results",
}


async def render_discovery_page(
    target: Message | CallbackQuery,
    category: str = "now_showing",
    page: int = 0,
    query: str | None = None,
    city: str = "Chennai",
    edit: bool = False,
):
    """Renders a single clean paginated view of movies for the given category."""
    movies = get_movie_catalog_by_category(category=category, city=city, query=query)
    page_items, total_pages, total_count = paginate_movies(movies, page=page, page_size=2)

    cat_title = CATEGORY_TITLES.get(category, "🎬 Movie Catalog")
    header = f"*{cat_title}* ({city})\n_Showing {len(page_items)} of {total_count} movies_\n"

    if not page_items:
        card_content = "\n_No movies found in this category right now._"
    else:
        cards = [format_movie_card(m, category=category) for m in page_items]
        card_content = "\n\n─────────────────────\n\n".join(cards)

    text = f"{header}\n{card_content}"
    markup = get_discovery_catalog_keyboard(
        category=category,
        page=page,
        total_pages=total_pages,
        movies=page_items,
    )

    if edit and isinstance(target, CallbackQuery):
        try:
            await target.message.edit_text(text, parse_mode="Markdown", reply_markup=markup)
        except Exception:
            pass
    elif isinstance(target, CallbackQuery):
        await target.message.answer(text, parse_mode="Markdown", reply_markup=markup)
    else:
        await target.answer(text, parse_mode="Markdown", reply_markup=markup)


@router.message(F.text == "🎬 Now Showing")
@router.message(Command("nowshowing"))
async def handle_now_showing(message: Message, state: FSMContext):
    await state.clear()
    async with get_db_session() as session:
        user, _ = await get_or_create_user(session, message.from_user.id)
        default_loc = await get_default_location(session, user.id)

    city = default_loc.normalized_city if default_loc else "Chennai"
    await render_discovery_page(message, category="now_showing", page=0, city=city)


@router.message(F.text == "🗓 Coming Soon")
@router.message(Command("comingsoon"))
async def handle_coming_soon(message: Message, state: FSMContext):
    await state.clear()
    async with get_db_session() as session:
        user, _ = await get_or_create_user(session, message.from_user.id)
        default_loc = await get_default_location(session, user.id)

    city = default_loc.normalized_city if default_loc else "Chennai"
    await render_discovery_page(message, category="coming_soon", page=0, city=city)


@router.message(Command("thisweek"))
async def handle_this_week(message: Message, state: FSMContext):
    await state.clear()
    await render_discovery_page(message, category="this_week", page=0)


@router.message(Command("thismonth"))
async def handle_this_month(message: Message, state: FSMContext):
    await state.clear()
    await render_discovery_page(message, category="this_month", page=0)


@router.message(Command("recent"))
async def handle_recent(message: Message, state: FSMContext):
    await state.clear()
    await render_discovery_page(message, category="recent", page=0)


@router.callback_query(F.data.startswith("disc_cat:"))
async def on_discovery_category_switch(query: CallbackQuery, state: FSMContext):
    category = query.data.split(":")[1]
    if category == "search":
        await state.set_state(DiscoveryFlow.searching)
        await query.message.answer(
            "🔍 *Search Movies:*\nType any movie title, actor, or genre (e.g. `Avatar`, `Rajinikanth`, `Action`):",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_disc_search")]
            ]),
        )
        await query.answer()
        return

    async with get_db_session() as session:
        user, _ = await get_or_create_user(session, query.from_user.id)
        default_loc = await get_default_location(session, user.id)

    city = default_loc.normalized_city if default_loc else "Chennai"
    await render_discovery_page(query, category=category, page=0, city=city, edit=True)
    await query.answer()


@router.callback_query(F.data.startswith("disc_p:"))
async def on_discovery_paginate(query: CallbackQuery):
    parts = query.data.split(":")
    category = parts[1]
    page = int(parts[2])

    async with get_db_session() as session:
        user, _ = await get_or_create_user(session, query.from_user.id)
        default_loc = await get_default_location(session, user.id)

    city = default_loc.normalized_city if default_loc else "Chennai"
    await render_discovery_page(query, category=category, page=page, city=city, edit=True)
    await query.answer()


@router.message(DiscoveryFlow.searching, F.text)
async def on_discovery_search_text(message: Message, state: FSMContext):
    q = message.text.strip()
    await state.clear()
    await render_discovery_page(message, category="search", page=0, query=q)


@router.callback_query(F.data == "cancel_disc_search")
async def on_cancel_search(query: CallbackQuery, state: FSMContext):
    await state.clear()
    await query.message.delete()
    await query.answer("Search cancelled.")


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
        await query.message.answer(
            f"📍 What is your city for *'{movie_title}'*?\n\n"
            "Please share your location or type your city name:",
            parse_mode="Markdown",
            reply_markup=get_location_request_keyboard(),
        )
        await state.set_state(TrackFlow.waiting_for_location)

    await query.answer()


@router.callback_query(F.data.startswith("disc_det:"))
async def on_discovery_details(query: CallbackQuery, state: FSMContext):
    movie_title = query.data.split(":", 1)[1]
    from ticketnotify.engine.discovery import MASTER_MOVIE_CATALOG, format_movie_card
    matched = None
    for m in MASTER_MOVIE_CATALOG:
        if m["title"].lower().startswith(movie_title.lower()) or movie_title.lower() in m["title"].lower():
            matched = m
            break
    if not matched:
        matched = {"title": movie_title, "formatted_release_date": "Confirmed", "languages": ["All"]}

    card_text = format_movie_card(matched, category="all")
    buttons = [
        [InlineKeyboardButton(text=f"🚨 Alert Me for '{movie_title[:20]}'", callback_data=f"disc_open:{movie_title[:25]}")],
        [InlineKeyboardButton(text="⬅️ Back to Catalog", callback_data="disc_cat:now_showing")],
    ]
    await query.message.answer(card_text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await query.answer()


@router.callback_query(F.data == "noop")
async def on_noop(query: CallbackQuery):
    await query.answer()
