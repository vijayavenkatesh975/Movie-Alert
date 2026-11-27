"""Handler for /theatres command with full city-wide manual selection, filters, and persistence."""

import logging
from typing import List, Set, Dict, Any, Optional
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from ticketnotify.database.session import get_db_session
from ticketnotify.database.crud import (
    get_or_create_user,
    get_default_location,
    get_user_alerts,
    get_alert_by_id,
    update_alert_cinemas,
    update_user_selected_theatres,
)
from ticketnotify.location.theatre_merger import (
    get_theatres_for_location,
    MergedCinema,
    get_unique_localities,
    get_unique_chains,
    filter_and_sort_theatres,
)
from ticketnotify.location.models import NormalizedLocation
from ticketnotify.bot.keyboards import (
    get_theatres_selection_keyboard,
    get_locality_filter_keyboard,
    get_chain_filter_keyboard,
    get_main_menu_keyboard,
)
from ticketnotify.bot.states import TheatresFlow

logger = logging.getLogger(__name__)
router = Router(name="theatres_router")


@router.message(F.text == "🏛 Theatres")
@router.message(Command("theatres"))
async def handle_theatres_command(message: Message, state: FSMContext):
    """Entry point for /theatres: offers Default City Theatres or Per-Alert Theatres."""
    await state.clear()
    async with get_db_session() as session:
        user, _ = await get_or_create_user(session, message.from_user.id)
        alerts = await get_user_alerts(session, user.id)
        loc = await get_default_location(session, user.id)

    city_name = loc.normalized_city if loc else "Chennai"

    buttons = [
        [
            InlineKeyboardButton(
                text=f"🏛 My Default Theatres ({city_name})",
                callback_data="th_scope:default",
            )
        ]
    ]

    if alerts:
        buttons.append([
            InlineKeyboardButton(
                text=f"🎬 Customise per Movie Alert ({len(alerts)} active)",
                callback_data="th_scope:per_alert",
            )
        ])

    buttons.append([InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_flow")])

    await message.answer(
        f"🏛 *Theatre Selection & Preferences*\n\n"
        f"📍 Active City: *{city_name}*\n"
        "Choose whether to manage your city-wide default theatres or configure theatres for a specific movie:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await state.set_state(TheatresFlow.choosing_scope)


@router.callback_query(TheatresFlow.choosing_scope, F.data == "th_scope:per_alert")
async def on_choose_per_alert_scope(query: CallbackQuery, state: FSMContext):
    async with get_db_session() as session:
        user, _ = await get_or_create_user(session, query.from_user.id)
        alerts = await get_user_alerts(session, user.id)

    if not alerts:
        await query.answer("No active alerts found. Use /track to start tracking movies!", show_alert=True)
        return

    buttons = []
    for a in alerts:
        city = a.location.normalized_city if a.location else "Chennai"
        buttons.append([
            InlineKeyboardButton(
                text=f"🎬 {a.movie_query} ({city})",
                callback_data=f"sel_alert_th:{a.id}",
            )
        ])
    buttons.append([InlineKeyboardButton(text="⬅️ Back", callback_data="th_scope:back")])

    await query.message.edit_text(
        "🎬 *Select which movie alert to customize theatres for:*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await state.set_state(TheatresFlow.choosing_alert)
    await query.answer()


@router.callback_query(TheatresFlow.choosing_alert, F.data == "th_scope:back")
async def on_back_to_scope(query: CallbackQuery, state: FSMContext):
    await handle_theatres_command(query.message, state)
    await query.answer()


@router.callback_query(TheatresFlow.choosing_scope, F.data == "th_scope:default")
async def on_choose_default_scope(query: CallbackQuery, state: FSMContext):
    """Loads city-wide theatres for the user's default city without radius cutoff."""
    async with get_db_session() as session:
        user, _ = await get_or_create_user(session, query.from_user.id)
        loc = await get_default_location(session, user.id)

    norm_loc = (
        NormalizedLocation(
            raw_query=loc.name,
            city=loc.normalized_city,
            country=loc.normalized_country,
            country_code=loc.country_code,
            latitude=loc.latitude,
            longitude=loc.longitude,
            display_name=f"{loc.normalized_city}, {loc.normalized_country}",
            platform_codes=loc.platform_mappings or {},
        )
        if loc
        else NormalizedLocation(
            raw_query="Chennai",
            city="Chennai",
            country="India",
            country_code="in",
            latitude=13.0827,
            longitude=80.2707,
            display_name="Chennai, India",
        )
    )

    # Retrieve all theatres in city without radius limit
    theatres = await get_theatres_for_location(location=norm_loc, radius_km=None)
    saved_theatres = (user.selected_theatres or {}).get("canonical_ids", [])
    selected_ids = set(saved_theatres)

    await state.update_data(
        edit_alert_id=None,  # None means user default theatres
        city_name=norm_loc.city,
        raw_theatres=[t.dict() for t in theatres],
        selected_ids=list(selected_ids),
        filter_locality="all",
        filter_chain="all",
        search_query="",
        sort_by="alpha",
        page=0,
    )

    await render_theatres_picker(query, state, edit=True)
    await state.set_state(TheatresFlow.selecting_theatres)
    await query.answer()


@router.callback_query(TheatresFlow.choosing_alert, F.data.startswith("sel_alert_th:"))
@router.callback_query(F.data.startswith("edit_theatres:"))
async def on_alert_chosen_for_theatres(query: CallbackQuery, state: FSMContext):
    alert_id = int(query.data.split(":")[1])
    async with get_db_session() as session:
        alert = await get_alert_by_id(session, alert_id)

    if not alert or not alert.location:
        await query.answer("Alert or location not found.", show_alert=True)
        return

    loc = alert.location
    norm_loc = NormalizedLocation(
        raw_query=loc.name,
        city=loc.normalized_city,
        country=loc.normalized_country,
        country_code=loc.country_code,
        latitude=loc.latitude,
        longitude=loc.longitude,
        display_name=f"{loc.normalized_city}, {loc.normalized_country}",
        platform_codes=loc.platform_mappings or {},
    )

    # City-wide theatre retrieval
    theatres = await get_theatres_for_location(location=norm_loc, radius_km=None)
    sel_data = alert.selected_cinemas or {}
    selected_ids = set(sel_data.get("canonical_ids", []))

    await state.update_data(
        edit_alert_id=alert_id,
        movie_title=alert.movie_query,
        city_name=norm_loc.city,
        raw_theatres=[t.dict() for t in theatres],
        selected_ids=list(selected_ids),
        filter_locality="all",
        filter_chain="all",
        search_query="",
        sort_by="alpha",
        page=0,
    )

    await render_theatres_picker(query, state, edit=True)
    await state.set_state(TheatresFlow.selecting_theatres)
    await query.answer()


async def render_theatres_picker(query: CallbackQuery, state: FSMContext, edit: bool = True):
    """Renders the current filtered, sorted, paginated theatre selection menu."""
    data = await state.get_data()
    city_name = data.get("city_name", "Chennai")
    edit_alert_id = data.get("edit_alert_id")
    movie_title = data.get("movie_title")
    raw_dicts = data.get("raw_theatres", [])
    selected_ids = set(data.get("selected_ids", []))
    loc_filter = data.get("filter_locality", "all")
    chain_filter = data.get("filter_chain", "all")
    search_query = data.get("search_query", "")
    sort_by = data.get("sort_by", "alpha")
    page = data.get("page", 0)

    theatres = [MergedCinema(**d) for d in raw_dicts]
    visible_theatres = filter_and_sort_theatres(
        theatres,
        locality=loc_filter,
        chain=chain_filter,
        query=search_query,
        sort_by=sort_by,
    )

    title_line = (
        f"🏛 *Theatre Preferences for {movie_title}*\n"
        if edit_alert_id
        else f"🏛 *Default Theatres in {city_name}*\n"
    )

    active_filters = []
    if loc_filter != "all":
        active_filters.append(f"Locality: {loc_filter}")
    if chain_filter != "all":
        active_filters.append(f"Chain: {chain_filter}")
    if search_query:
        active_filters.append(f"Search: '{search_query}'")
    filter_str = f"🔍 *Filters:* {', '.join(active_filters)}\n" if active_filters else ""

    text = (
        f"{title_line}"
        f"📍 City: *{city_name}* (Total {len(theatres)} available)\n"
        f"Selected: *{len(selected_ids)}* theatres | Showing *{len(visible_theatres)}*\n"
        f"{filter_str}\n"
        "Tap any theatre to toggle selection. Use filters or search to browse by area."
    )

    markup = get_theatres_selection_keyboard(
        theatres=visible_theatres,
        selected_ids=selected_ids,
        page=page,
        page_size=5,
        current_locality=loc_filter,
        current_chain=chain_filter,
        sort_by=sort_by,
    )

    if edit:
        try:
            await query.message.edit_text(text, parse_mode="Markdown", reply_markup=markup)
        except Exception:
            pass
    else:
        await query.message.answer(text, parse_mode="Markdown", reply_markup=markup)


@router.callback_query(TheatresFlow.selecting_theatres, F.data.startswith("th_tog:"))
async def on_toggle_theatre(query: CallbackQuery, state: FSMContext):
    parts = query.data.split(":")
    cid = parts[1]
    page = int(parts[2]) if len(parts) > 2 else 0

    data = await state.get_data()
    selected = set(data.get("selected_ids", []))
    if cid in selected:
        selected.remove(cid)
    else:
        selected.add(cid)

    await state.update_data(selected_ids=list(selected), page=page)
    await render_theatres_picker(query, state, edit=True)
    await query.answer()


@router.callback_query(TheatresFlow.selecting_theatres, F.data.startswith("th_page:"))
async def on_paginate_theatres(query: CallbackQuery, state: FSMContext):
    page = int(query.data.split(":")[1])
    await state.update_data(page=page)
    await render_theatres_picker(query, state, edit=True)
    await query.answer()


@router.callback_query(TheatresFlow.selecting_theatres, F.data.startswith("th_act:"))
async def on_theatre_action(query: CallbackQuery, state: FSMContext):
    parts = query.data.split(":")
    act = parts[1]
    page = int(parts[2]) if len(parts) > 2 else 0

    data = await state.get_data()
    raw_dicts = data.get("raw_theatres", [])
    theatres = [MergedCinema(**d) for d in raw_dicts]
    selected = set(data.get("selected_ids", []))
    alert_id = data.get("edit_alert_id")
    city_name = data.get("city_name", "Chennai")

    if act == "all":
        # Select all visible theatres
        loc_filter = data.get("filter_locality", "all")
        chain_filter = data.get("filter_chain", "all")
        query_str = data.get("search_query", "")
        sort_by = data.get("sort_by", "alpha")
        vis = filter_and_sort_theatres(theatres, loc_filter, chain_filter, query_str, sort_by)
        for t in vis:
            selected.add(t.canonical_id)
        await state.update_data(selected_ids=list(selected))
        await render_theatres_picker(query, state, edit=True)
        await query.answer("Selected all!")
        return

    elif act == "clear":
        # Clear all selections
        await state.update_data(selected_ids=[])
        await render_theatres_picker(query, state, edit=True)
        await query.answer("Cleared all selections.")
        return

    elif act == "filt_loc":
        # Show locality buttons
        localities = get_unique_localities(theatres)
        curr_loc = data.get("filter_locality")
        await query.message.edit_text(
            f"📍 *Choose Locality / Area in {city_name}:*",
            parse_mode="Markdown",
            reply_markup=get_locality_filter_keyboard(localities, curr_loc),
        )
        await query.answer()
        return

    elif act == "filt_chain":
        # Show chain buttons
        chains = get_unique_chains(theatres)
        curr_chain = data.get("filter_chain")
        await query.message.edit_text(
            f"🏢 *Choose Cinema Chain in {city_name}:*",
            parse_mode="Markdown",
            reply_markup=get_chain_filter_keyboard(chains, curr_chain),
        )
        await query.answer()
        return

    elif act == "sort_distance":
        await state.update_data(sort_by="distance", page=0)
        await render_theatres_picker(query, state, edit=True)
        await query.answer("Sorted by distance.")
        return

    elif act == "sort_alpha":
        await state.update_data(sort_by="alpha", page=0)
        await render_theatres_picker(query, state, edit=True)
        await query.answer("Sorted alphabetically (A-Z).")
        return

    elif act == "search":
        await state.set_state(TheatresFlow.searching_theatre)
        await query.message.answer(
            "🔍 *Search Theatres:*\nType any cinema name or mall (e.g. `Palazzo`, `Phoenix`, `Express Avenue`):",
            parse_mode="Markdown",
        )
        await query.answer()
        return

    elif act == "back":
        await render_theatres_picker(query, state, edit=True)
        await query.answer()
        return

    elif act == "done":
        # Build platform mappings and canonical names
        platform_mapping: Dict[str, List[str]] = {}
        canonical_names: List[str] = []

        for t in theatres:
            if t.canonical_id in selected:
                canonical_names.append(t.name)
                for plat, p_cid in t.platform_cinema_ids.items():
                    platform_mapping.setdefault(plat, []).append(p_cid)

        save_dict = {
            "city": city_name,
            "canonical_ids": list(selected),
            "platform_cinema_ids": platform_mapping,
            "names": canonical_names,
        }

        async with get_db_session() as session:
            user, _ = await get_or_create_user(session, query.from_user.id)
            if alert_id is not None:
                # Per-alert selection persistence
                await update_alert_cinemas(session, alert_id, save_dict)
                count = len(selected)
                msg_txt = (
                    f"✅ *Saved theatre selection for alert!*\n"
                    f"Monitoring *{count}* theatres in {city_name}."
                    if count
                    else f"✅ Alert will monitor *all* theatres in {city_name}."
                )
            else:
                # User default city-wide selection persistence
                await update_user_selected_theatres(session, user.id, save_dict)
                count = len(selected)
                msg_txt = (
                    f"🎉 *Saved your default theatres for {city_name}!*\n"
                    f"You have selected *{count}* theatres. New movie watches will track these theatres automatically."
                    if count
                    else f"✅ Saved! All theatres in {city_name} will be tracked by default."
                )

        await query.message.edit_text(msg_txt, parse_mode="Markdown")
        await state.clear()
        await query.answer()
        return


@router.callback_query(TheatresFlow.selecting_theatres, F.data.startswith("th_setloc:"))
async def on_set_locality(query: CallbackQuery, state: FSMContext):
    loc = query.data.split(":")[1]
    await state.update_data(filter_locality=loc, page=0)
    await render_theatres_picker(query, state, edit=True)
    await query.answer(f"Locality: {loc}")


@router.callback_query(TheatresFlow.selecting_theatres, F.data.startswith("th_setchain:"))
async def on_set_chain(query: CallbackQuery, state: FSMContext):
    chain = query.data.split(":")[1]
    await state.update_data(filter_chain=chain, page=0)
    await render_theatres_picker(query, state, edit=True)
    await query.answer(f"Chain: {chain}")


@router.message(TheatresFlow.searching_theatre, F.text)
async def on_theatre_search_input(message: Message, state: FSMContext):
    q = message.text.strip()
    await state.set_state(TheatresFlow.selecting_theatres)
    await state.update_data(search_query=q, page=0)

    # Fake a query-like object or send new picker
    data = await state.get_data()
    raw_dicts = data.get("raw_theatres", [])
    theatres = [MergedCinema(**d) for d in raw_dicts]
    selected_ids = set(data.get("selected_ids", []))
    city_name = data.get("city_name", "Chennai")

    vis = filter_and_sort_theatres(theatres, query=q)
    markup = get_theatres_selection_keyboard(
        theatres=vis,
        selected_ids=selected_ids,
        page=0,
        page_size=5,
    )
    await message.answer(
        f"🔍 Found *{len(vis)}* theatres matching '{q}' in {city_name}:\n"
        "Tap to toggle your preferred cinemas:",
        parse_mode="Markdown",
        reply_markup=markup,
    )
