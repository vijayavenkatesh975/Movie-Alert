"""Guided multi-step /track flow handler."""

import asyncio
import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove

from ticketnotify.bot.states import TrackFlow
from ticketnotify.bot.keyboards import (
    get_location_request_keyboard,
    get_movie_matches_keyboard,
    get_platform_selection_keyboard,
    get_filter_builder_keyboard,
    get_theatres_selection_keyboard,
    get_seat_preferences_keyboard,
    get_urgency_keyboard,
)
from ticketnotify.database.session import get_db_session
from ticketnotify.database.crud import (
    get_or_create_user,
    get_default_location,
    create_location,
    create_alert,
)
from ticketnotify.location import geocoder, map_location_to_platforms
from ticketnotify.location.theatre_merger import get_theatres_for_location, MergedCinema
from ticketnotify.adapters.registry import registry
from ticketnotify.engine.scheduler import scheduler

logger = logging.getLogger(__name__)
router = Router(name="track_router")


@router.message(Command("track"))
async def start_track_flow(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "🎬 *Step 1 of 4: Which movie would you like to track?*\n\n"
        "Please type the name of the movie (e.g. `Avatar: Fire and Ash`, `Kalki 2898 AD`, `Deadpool`):",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )
    await state.set_state(TrackFlow.waiting_for_movie_title)


@router.message(TrackFlow.waiting_for_movie_title)
async def process_movie_title(message: Message, state: FSMContext):
    title = message.text.strip()
    if not title:
        await message.answer("Please enter a valid movie title.")
        return

    await state.update_data(movie_query=title)

    # Check if user already has a default location
    async with get_db_session() as session:
        user, _ = await get_or_create_user(session, message.from_user.id)
        default_loc = await get_default_location(session, user.id)

    if default_loc:
        # Reconstruct normalized location
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
        await search_and_present_matches(message, state, title, norm_loc)
    else:
        # Prompt for location
        await message.answer(
            f"📍 *Step 2 of 4: Location for '{title}'*\n\n"
            "Tell me your location. You can enter:\n"
            "• City name (e.g. `Bengaluru`, `Mumbai`, `London`, `Dubai`)\n"
            "• Area or Pincode (e.g. `Koramangala 560034`, `10001`)\n"
            "• Or tap the button below to share your GPS location:",
            parse_mode="Markdown",
            reply_markup=get_location_request_keyboard(),
        )
        await state.set_state(TrackFlow.waiting_for_location)


@router.message(TrackFlow.waiting_for_location, F.location)
async def process_location_gps(message: Message, state: FSMContext):
    lat = message.location.latitude
    lng = message.location.longitude

    wait_msg = await message.answer("🔍 Resolving GPS location...", reply_markup=ReplyKeyboardRemove())
    norm_loc = await geocoder.reverse_geocode(lat, lng)

    if not norm_loc:
        await wait_msg.edit_text("Could not resolve location. Please type your city name manually:")
        return

    await save_resolved_location(message, state, norm_loc)


@router.message(TrackFlow.waiting_for_location, F.text)
async def process_location_text(message: Message, state: FSMContext):
    if message.text == "❌ Cancel":
        await state.clear()
        await message.answer("Tracking setup cancelled.", reply_markup=ReplyKeyboardRemove())
        return

    query_text = message.text.strip()
    wait_msg = await message.answer(f"🔍 Geocoding '{query_text}'...", reply_markup=ReplyKeyboardRemove())
    norm_loc = await geocoder.geocode(query_text)

    if not norm_loc:
        await wait_msg.edit_text(
            f"❌ Could not find '{query_text}'. Please try another city name or area:"
        )
        return

    await save_resolved_location(message, state, norm_loc)


async def save_resolved_location(message: Message, state: FSMContext, norm_loc):
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
        loc_id = loc.id

    await state.update_data(
        location_id=loc_id,
        location_obj=norm_loc.dict(),
    )
    data = await state.get_data()
    title = data.get("movie_query", "")
    await search_and_present_matches(message, state, title, norm_loc)


async def search_and_present_matches(message: Message, state: FSMContext, title: str, norm_loc):
    wait_msg = await message.answer(f"🔍 Searching platforms in *{norm_loc.city}* for *'{title}'*...", parse_mode="Markdown")

    supported = norm_loc.supported_platforms or ["bms", "ticketnew", "district", "pvrinox"]
    all_matches = []
    
    # Query supported platforms
    for p in supported:
        matches = await registry.search_movie(p, title, norm_loc)
        for m in matches:
            all_matches.append(m.dict())

    # De-duplicate by title
    unique_matches = []
    seen_titles = set()
    for m in all_matches:
        t_key = m["title"].lower().strip()
        if t_key not in seen_titles:
            seen_titles.add(t_key)
            unique_matches.append(m)

    if not unique_matches:
        # Fallback to direct query
        unique_matches = [{
            "movie_id": f"Q_{hash(title) % 10000000:07d}",
            "title": title.title(),
            "platform": supported[0] if supported else "bms",
            "languages": ["All Languages"],
            "formats": ["2D", "3D", "IMAX"],
        }]

    await state.update_data(matched_movies=unique_matches)
    await wait_msg.delete()

    await message.answer(
        f"🎯 *Select the exact movie you want to track:*",
        parse_mode="Markdown",
        reply_markup=get_movie_matches_keyboard(unique_matches),
    )
    await state.set_state(TrackFlow.selecting_movie_match)


@router.callback_query(TrackFlow.selecting_movie_match, F.data.startswith("sel_movie:"))
async def on_movie_selected(query: CallbackQuery, state: FSMContext):
    idx = int(query.data.split(":")[1])
    data = await state.get_data()
    matches = data.get("matched_movies", [])

    if idx >= len(matches):
        await query.answer("Selection error. Please try again.")
        return

    chosen = matches[idx]
    loc_data = data.get("location_obj", {})
    supported = loc_data.get("supported_platforms", ["bms", "ticketnew", "district", "pvrinox"])
    unsupported = loc_data.get("unsupported_platforms", [])

    # Default select all supported platforms
    selected = set(supported)
    await state.update_data(
        selected_movie=chosen,
        selected_platforms=list(selected),
    )

    unsupported_note = ""
    if unsupported:
        unsupported_note = f"\n\n⚠️ *Unavailable in {loc_data.get('country')}:* {', '.join(unsupported).upper()}"

    await query.message.edit_text(
        f"🎬 *Selected Movie:* {chosen['title']}\n"
        f"📍 *Location:* {loc_data.get('city')}, {loc_data.get('country')}\n\n"
        f"🏷 *Step 3 of 4: Booking Platforms*\n"
        f"Select which platforms you want to monitor (each will send its own separate alert):"
        f"{unsupported_note}",
        parse_mode="Markdown",
        reply_markup=get_platform_selection_keyboard(supported, selected),
    )
    await state.set_state(TrackFlow.selecting_platforms)
    await query.answer()


@router.callback_query(TrackFlow.selecting_platforms, F.data.startswith("toggle_plat:"))
async def toggle_platform(query: CallbackQuery, state: FSMContext):
    p = query.data.split(":")[1]
    data = await state.get_data()
    selected = set(data.get("selected_platforms", []))
    loc_data = data.get("location_obj", {})
    supported = loc_data.get("supported_platforms", ["bms", "ticketnew", "district", "pvrinox"])

    if p in selected:
        selected.remove(p)
    else:
        selected.add(p)

    await state.update_data(selected_platforms=list(selected))
    await query.message.edit_reply_markup(
        reply_markup=get_platform_selection_keyboard(supported, selected)
    )
    await query.answer()


@router.callback_query(TrackFlow.selecting_platforms, F.data == "confirm_platforms")
async def confirm_platforms(query: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected = data.get("selected_platforms", [])

    if not selected:
        await query.answer("Please select at least one platform!", show_alert=True)
        return

    loc_dict = data.get("location_obj", {})
    from ticketnotify.location.models import NormalizedLocation
    norm_loc = NormalizedLocation(**loc_dict) if loc_dict else None

    # Step 3.5: Fetch all cinemas in the city (no radius cutoff)
    theatres: List[MergedCinema] = []
    default_selected: List[str] = []
    if norm_loc:
        theatres = await get_theatres_for_location(norm_loc, platforms=selected, radius_km=None)
        async with get_db_session() as session:
            u, _ = await get_or_create_user(session, query.from_user.id)
            if u and u.selected_theatres:
                default_selected = u.selected_theatres.get("canonical_ids", [])

    await state.update_data(
        theatres_list=[t.dict() for t in theatres],
        selected_theatre_ids=default_selected,
    )

    if theatres:
        count_msg = f" (Pre-selected your {len(default_selected)} saved favourites)" if default_selected else ""
        await query.message.edit_text(
            f"🏛 *Step 3b: Choose Theatres in {norm_loc.city}*\n\n"
            f"Found {len(theatres)} available theatres in the city.{count_msg}\n"
            f"Select specific theatres or tap *Continue* to monitor all:",
            parse_mode="Markdown",
            reply_markup=get_theatres_selection_keyboard(theatres, set(default_selected), page=0),
        )
        await state.set_state(TrackFlow.selecting_theatres)
    else:
        # If no theatres found, proceed directly to filters
        filters = {"formats": [], "max_price": None, "min_seats": None}
        await state.update_data(filters=filters)
        await query.message.edit_text(
            "⚙️ *Step 4: Filters & Preferences*\n\n"
            "You can customize formats (IMAX, 3D, 4DX), maximum price, or minimum seats needed.\n"
            "Or tap *Done* to track all shows with default settings!",
            parse_mode="Markdown",
            reply_markup=get_filter_builder_keyboard(filters),
        )
        await state.set_state(TrackFlow.configuring_filters)

    await query.answer()


@router.callback_query(TrackFlow.selecting_theatres, F.data.startswith("th_tog:"))
async def on_track_toggle_theatre(query: CallbackQuery, state: FSMContext):
    parts = query.data.split(":")
    cid = parts[1]
    page = int(parts[2]) if len(parts) > 2 else 0

    data = await state.get_data()
    selected = set(data.get("selected_theatre_ids", []))
    theatres_dicts = data.get("theatres_list", [])
    theatres = [MergedCinema(**d) for d in theatres_dicts]

    if cid in selected:
        selected.remove(cid)
    else:
        selected.add(cid)

    await state.update_data(selected_theatre_ids=list(selected))
    await query.message.edit_reply_markup(
        reply_markup=get_theatres_selection_keyboard(theatres, selected, page=page)
    )
    await query.answer()


@router.callback_query(TrackFlow.selecting_theatres, F.data.startswith("th_page:"))
async def on_track_page_theatres(query: CallbackQuery, state: FSMContext):
    page = int(query.data.split(":")[1])
    data = await state.get_data()
    selected = set(data.get("selected_theatre_ids", []))
    theatres_dicts = data.get("theatres_list", [])
    theatres = [MergedCinema(**d) for d in theatres_dicts]

    await query.message.edit_reply_markup(
        reply_markup=get_theatres_selection_keyboard(theatres, selected, page=page)
    )
    await query.answer()


@router.callback_query(TrackFlow.selecting_theatres, F.data.startswith("th_act:"))
async def on_track_action_theatres(query: CallbackQuery, state: FSMContext):
    parts = query.data.split(":")
    act = parts[1]
    page = int(parts[2]) if len(parts) > 2 else 0

    data = await state.get_data()
    theatres_dicts = data.get("theatres_list", [])
    theatres = [MergedCinema(**d) for d in theatres_dicts]
    selected = set(data.get("selected_theatre_ids", []))

    if act == "all":
        selected = {t.canonical_id for t in theatres}
        await state.update_data(selected_theatre_ids=list(selected))
        await query.message.edit_reply_markup(reply_markup=get_theatres_selection_keyboard(theatres, selected, page=page))
        await query.answer("Selected all!")
        return
    elif act == "clear":
        await state.update_data(selected_theatre_ids=[])
        await query.message.edit_reply_markup(reply_markup=get_theatres_selection_keyboard(theatres, set(), page=page))
        await query.answer("Cleared selections.")
        return
    elif act == "near5":
        selected = {t.canonical_id for t in theatres[:5]}
        await state.update_data(selected_theatre_ids=list(selected))
        await query.message.edit_reply_markup(reply_markup=get_theatres_selection_keyboard(theatres, selected, page=page))
        await query.answer()
        return
    elif act == "chains":
        selected = {t.canonical_id for t in theatres if t.chain in ("PVR", "INOX", "Cinepolis", "AGS", "Rohini", "Miraj", "MovieMax")}
        await state.update_data(selected_theatre_ids=list(selected))
        await query.message.edit_reply_markup(reply_markup=get_theatres_selection_keyboard(theatres, selected, page=page))
        await query.answer()
        return
    elif act == "done":
        # Advance to filters
        filters = {"formats": [], "max_price": None, "min_seats": None}
        await state.update_data(filters=filters)
        await query.message.edit_text(
            "⚙️ *Step 4 of 6: Format & Price Filters*\n\n"
            "You can customize formats (IMAX, 3D, 4DX), maximum price, or minimum seats.\n"
            "Or tap *Done* to continue:",
            parse_mode="Markdown",
            reply_markup=get_filter_builder_keyboard(filters),
        )
        await state.set_state(TrackFlow.configuring_filters)
        await query.answer()


@router.callback_query(TrackFlow.configuring_filters, F.data.startswith("toggle_filter:"))
async def toggle_filter_option(query: CallbackQuery, state: FSMContext):
    opt = query.data.split(":")[1]
    data = await state.get_data()
    filters = data.get("filters", {})
    formats = filters.get("formats", [])

    if opt == "fmt_imax":
        formats = [f for f in formats if f != "IMAX"] if "IMAX" in formats else formats + ["IMAX"]
    elif opt == "fmt_3d":
        formats = [f for f in formats if f != "3D"] if "3D" in formats else formats + ["3D"]
    elif opt == "fmt_4dx":
        formats = [f for f in formats if f != "4DX"] if "4DX" in formats else formats + ["4DX"]
    elif opt == "fmt_all":
        formats = []

    filters["formats"] = formats
    await state.update_data(filters=filters)
    await query.message.edit_reply_markup(reply_markup=get_filter_builder_keyboard(filters))
    await query.answer()


@router.callback_query(TrackFlow.configuring_filters, F.data == "filters_done")
async def finish_filters_step(query: CallbackQuery, state: FSMContext):
    # Advance to seat preferences
    seat_prefs = {
        "seats_needed": 1,
        "must_be_consecutive": True,
        "row_zone": "any",
        "column_zone": "any",
        "seat_category": "any",
    }
    await state.update_data(seat_prefs=seat_prefs)
    await query.message.edit_text(
        "💺 *Step 5 of 6: Seat Preferences*\n\n"
        "Configure group size (1-10), row zone (front/middle/back), column zone (center/aisle), and category:",
        parse_mode="Markdown",
        reply_markup=get_seat_preferences_keyboard(seat_prefs),
    )
    await state.set_state(TrackFlow.configuring_seats)
    await query.answer()


@router.callback_query(TrackFlow.configuring_seats, F.data == "seat_cycle_needed")
async def on_track_seat_cycle_needed(query: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    prefs = data.get("seat_prefs", {})
    needed = prefs.get("seats_needed", 1)
    prefs["seats_needed"] = (needed % 10) + 1
    await state.update_data(seat_prefs=prefs)
    await query.message.edit_reply_markup(reply_markup=get_seat_preferences_keyboard(prefs))
    await query.answer()


@router.callback_query(TrackFlow.configuring_seats, F.data == "seat_toggle_consec")
async def on_track_seat_toggle_consec(query: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    prefs = data.get("seat_prefs", {})
    prefs["must_be_consecutive"] = not prefs.get("must_be_consecutive", True)
    await state.update_data(seat_prefs=prefs)
    await query.message.edit_reply_markup(reply_markup=get_seat_preferences_keyboard(prefs))
    await query.answer()


@router.callback_query(TrackFlow.configuring_seats, F.data == "seat_cycle_row")
async def on_track_seat_cycle_row(query: CallbackQuery, state: FSMContext):
    zones = ["any", "front", "middle", "back"]
    data = await state.get_data()
    prefs = data.get("seat_prefs", {})
    curr = prefs.get("row_zone", "any")
    next_idx = (zones.index(curr) + 1) % len(zones) if curr in zones else 0
    prefs["row_zone"] = zones[next_idx]
    await state.update_data(seat_prefs=prefs)
    await query.message.edit_reply_markup(reply_markup=get_seat_preferences_keyboard(prefs))
    await query.answer()


@router.callback_query(TrackFlow.configuring_seats, F.data == "seat_cycle_col")
async def on_track_seat_cycle_col(query: CallbackQuery, state: FSMContext):
    zones = ["any", "center", "left", "right", "aisle"]
    data = await state.get_data()
    prefs = data.get("seat_prefs", {})
    curr = prefs.get("column_zone", "any")
    next_idx = (zones.index(curr) + 1) % len(zones) if curr in zones else 0
    prefs["column_zone"] = zones[next_idx]
    await state.update_data(seat_prefs=prefs)
    await query.message.edit_reply_markup(reply_markup=get_seat_preferences_keyboard(prefs))
    await query.answer()


@router.callback_query(TrackFlow.configuring_seats, F.data == "seat_cycle_cat")
async def on_track_seat_cycle_cat(query: CallbackQuery, state: FSMContext):
    cats = ["any", "Recliner", "Premium", "Gold", "Silver"]
    data = await state.get_data()
    prefs = data.get("seat_prefs", {})
    curr = prefs.get("seat_category", "any")
    next_idx = (cats.index(curr) + 1) % len(cats) if curr in cats else 0
    prefs["seat_category"] = cats[next_idx]
    await state.update_data(seat_prefs=prefs)
    await query.message.edit_reply_markup(reply_markup=get_seat_preferences_keyboard(prefs))
    await query.answer()


@router.callback_query(TrackFlow.configuring_seats, F.data == "seat_prefs_done")
async def on_track_seat_prefs_done(query: CallbackQuery, state: FSMContext):
    # Advance to urgency
    await state.update_data(urgency="WARM")
    await query.message.edit_text(
        "⚡ *Step 6 of 6: Alert Polling Speed*\n\n"
        "Choose how aggressively to monitor this movie:\n"
        "• *Hot (1-3s)*: For movies expected to open within 24h\n"
        "• *Normal (10-15s)*: Standard real-time monitoring\n"
        "• *Passive (1-2 min)*: Background checks for distant releases",
        parse_mode="Markdown",
        reply_markup=get_urgency_keyboard("WARM"),
    )
    await state.set_state(TrackFlow.selecting_urgency)
    await query.answer()


@router.callback_query(TrackFlow.selecting_urgency, F.data.startswith("urg_set:"))
async def on_track_set_urgency(query: CallbackQuery, state: FSMContext):
    urg = query.data.split(":")[1]
    await state.update_data(urgency=urg)
    await query.message.edit_reply_markup(reply_markup=get_urgency_keyboard(urg))
    await query.answer()


@router.callback_query(TrackFlow.selecting_urgency, F.data == "urg_confirm")
async def finalize_track_flow(query: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    movie = data.get("selected_movie", {})
    loc_data = data.get("location_obj", {})
    loc_id = data.get("location_id")
    platforms = data.get("selected_platforms", ["bms"])
    filters = data.get("filters", {})
    seat_prefs = data.get("seat_prefs", {})
    urgency = data.get("urgency", "WARM")

    # Build selected cinemas dictionary
    theatres_dicts = data.get("theatres_list", [])
    selected_cids = set(data.get("selected_theatre_ids", []))
    theatres = [MergedCinema(**d) for d in theatres_dicts]

    platform_mapping: Dict[str, List[str]] = {}
    canonical_names: List[str] = []
    if selected_cids:
        for t in theatres:
            if t.canonical_id in selected_cids:
                canonical_names.append(t.name)
                for plat, p_cid in t.platform_cinema_ids.items():
                    platform_mapping.setdefault(plat, []).append(p_cid)

    selected_cinemas_dict = {
        "canonical_ids": list(selected_cids),
        "platform_cinema_ids": platform_mapping,
        "names": canonical_names,
    }

    async with get_db_session() as session:
        user, _ = await get_or_create_user(session, query.from_user.id)
        alert = await create_alert(
            session=session,
            user_id=user.id,
            movie_query=movie.get("title", data.get("movie_query")),
            location_id=loc_id,
            platforms=platforms,
            movie_ids_by_platform={p: movie.get("movie_id", "") for p in platforms},
            selected_cinemas=selected_cinemas_dict,
            filters_json=filters,
            seats_needed=seat_prefs.get("seats_needed", 1),
            must_be_consecutive=seat_prefs.get("must_be_consecutive", True),
            row_zone=seat_prefs.get("row_zone", "any"),
            column_zone=seat_prefs.get("column_zone", "any"),
            seat_category=seat_prefs.get("seat_category", "any"),
            urgency=urgency,
        )

    await state.clear()

    platform_names = {
        "bms": "BookMyShow",
        "ticketnew": "Ticketnew",
        "district": "District (Zomato)",
        "pvrinox": "PVR INOX",
    }
    plat_str = ", ".join([platform_names.get(p, p.upper()) for p in platforms])
    fmt_str = ", ".join(filters.get("formats", [])) or "All formats (2D/3D/IMAX/4DX)"
    theatre_str = f"{len(selected_cids)} selected" if selected_cids else f"All within 10 km ({len(theatres)} theatres)"

    success_text = (
        f"🎉 *ALERT ACTIVATED!*\n\n"
        f"🎬 *Movie:* {movie.get('title')}\n"
        f"📍 *Location:* {loc_data.get('city')}, {loc_data.get('country')}\n"
        f"🏛 *Theatres:* {theatre_str}\n"
        f"🏷 *Platforms:* {plat_str}\n"
        f"🎯 *Formats:* {fmt_str}\n"
        f"💺 *Seats:* {seat_prefs.get('seats_needed', 1)} ({seat_prefs.get('seat_category', 'any').title()})\n"
        f"⚡ *Polling Speed:* {urgency} tier\n\n"
        "⚡ We are monitoring ticket counters continuously. "
        "You will receive an instant notification with direct booking links the moment bookings open!"
    )

    await query.message.edit_text(success_text, parse_mode="Markdown")
    await query.answer()

    # Trigger single poll cycle right away so if tickets are ALREADY live, user gets notified immediately
    asyncio.create_task(scheduler.poll_once())


@router.callback_query(F.data == "cancel_flow")
async def cancel_flow_callback(query: CallbackQuery, state: FSMContext):
    await state.clear()
    await query.message.edit_text("❌ Action cancelled.")
    await query.answer()
