"""Handler for /theatres command to manage cinema selections for active alerts."""

import logging
from typing import List, Set, Dict, Any
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from ticketnotify.database.session import get_db_session
from ticketnotify.database.crud import (
    get_user_by_telegram_id,
    get_user_alerts,
    get_alert_by_id,
    update_alert_cinemas,
)
from ticketnotify.location.theatre_merger import get_theatres_for_location, MergedCinema
from ticketnotify.location.models import NormalizedLocation
from ticketnotify.bot.keyboards import get_theatres_selection_keyboard
from ticketnotify.bot.states import TheatresFlow

logger = logging.getLogger(__name__)
router = Router(name="theatres_router")


@router.message(F.text == "🏛 Theatres")
@router.message(Command("theatres"))
async def handle_theatres_command(message: Message, state: FSMContext):
    await state.clear()
    async with get_db_session() as session:
        user = await get_user_by_telegram_id(session, message.from_user.id)
        if not user:
            await message.answer("You don't have any active alerts yet. Use /track to get started!")
            return
        alerts = await get_user_alerts(session, user.id)

    if not alerts:
        await message.answer("You have no active alerts to configure theatres for.")
        return

    buttons = []
    for a in alerts:
        city = a.location.normalized_city if a.location else "Global"
        buttons.append([
            InlineKeyboardButton(
                text=f"🎬 {a.movie_query} ({city})",
                callback_data=f"sel_alert_th:{a.id}",
            )
        ])
    buttons.append([InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_flow")])

    await message.answer(
        "🏛 *Select an alert to customize theatre selection:*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await state.set_state(TheatresFlow.choosing_alert)


@router.callback_query(TheatresFlow.choosing_alert, F.data.startswith("sel_alert_th:"))
@router.callback_query(F.data.startswith("edit_theatres:"))
async def on_alert_chosen_for_theatres(query: CallbackQuery, state: FSMContext):
    alert_id = int(query.data.split(":")[1])
    async with get_db_session() as session:
        alert = await get_alert_by_id(session, alert_id)

    if not alert or not alert.location:
        await query.answer("Alert or location not found.", show_alert=True)
        return

    # Build normalized location
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

    theatres = await get_theatres_for_location(
        location=norm_loc,
        platforms=alert.platforms,
        radius_km=alert.location.radius_km or 10.0,
    )

    # Selected canonical IDs
    sel_data = alert.selected_cinemas or {}
    selected_ids = set(sel_data.get("canonical_ids", []))

    await state.update_data(
        edit_alert_id=alert_id,
        theatres_list=[t.dict() for t in theatres],
        selected_ids=list(selected_ids),
    )

    await query.message.edit_text(
        f"🏛 *Theatre Selection for {alert.movie_query}*\n"
        f"📍 Location: {norm_loc.city} ({len(theatres)} theatres in radius)\n\n"
        "Tap theatres to toggle them, or use the quick buttons below. "
        "If none are selected, all theatres in radius are monitored.",
        parse_mode="Markdown",
        reply_markup=get_theatres_selection_keyboard(theatres, selected_ids, page=0),
    )
    await state.set_state(TheatresFlow.selecting_theatres)
    await query.answer()


@router.callback_query(TheatresFlow.selecting_theatres, F.data.startswith("th_tog:"))
async def on_toggle_theatre_alert(query: CallbackQuery, state: FSMContext):
    parts = query.data.split(":")
    cid = parts[1]
    page = int(parts[2]) if len(parts) > 2 else 0

    data = await state.get_data()
    selected = set(data.get("selected_ids", []))
    theatres_dicts = data.get("theatres_list", [])
    theatres = [MergedCinema(**d) for d in theatres_dicts]

    if cid in selected:
        selected.remove(cid)
    else:
        selected.add(cid)

    await state.update_data(selected_ids=list(selected))
    await query.message.edit_reply_markup(
        reply_markup=get_theatres_selection_keyboard(theatres, selected, page=page)
    )
    await query.answer()


@router.callback_query(TheatresFlow.selecting_theatres, F.data.startswith("th_page:"))
async def on_page_theatres_alert(query: CallbackQuery, state: FSMContext):
    page = int(query.data.split(":")[1])
    data = await state.get_data()
    selected = set(data.get("selected_ids", []))
    theatres_dicts = data.get("theatres_list", [])
    theatres = [MergedCinema(**d) for d in theatres_dicts]

    await query.message.edit_reply_markup(
        reply_markup=get_theatres_selection_keyboard(theatres, selected, page=page)
    )
    await query.answer()


@router.callback_query(TheatresFlow.selecting_theatres, F.data.startswith("th_act:"))
async def on_action_theatres_alert(query: CallbackQuery, state: FSMContext):
    parts = query.data.split(":")
    act = parts[1]
    page = int(parts[2]) if len(parts) > 2 else 0

    data = await state.get_data()
    theatres_dicts = data.get("theatres_list", [])
    theatres = [MergedCinema(**d) for d in theatres_dicts]
    selected = set(data.get("selected_ids", []))
    alert_id = data.get("edit_alert_id")

    if act == "all":
        selected = {t.canonical_id for t in theatres}
    elif act == "near5":
        selected = {t.canonical_id for t in theatres[:5]}
    elif act == "chains":
        selected = {t.canonical_id for t in theatres if t.chain in ("PVR", "INOX", "Cinepolis", "Miraj", "MovieMax")}
    elif act == "done":
        # Save to database
        # Map selected canonical IDs to per-platform cinema IDs
        platform_mapping: Dict[str, List[str]] = {}
        canonical_names: List[str] = []

        for t in theatres:
            if t.canonical_id in selected:
                canonical_names.append(t.name)
                for plat, p_cid in t.platform_cinema_ids.items():
                    platform_mapping.setdefault(plat, []).append(p_cid)

        save_dict = {
            "canonical_ids": list(selected),
            "platform_cinema_ids": platform_mapping,
            "names": canonical_names,
        }

        async with get_db_session() as session:
            await update_alert_cinemas(session, alert_id, save_dict)

        count = len(selected)
        txt = f"✅ Updated theatre preferences! ({count} selected)" if count else "✅ Alert will monitor all theatres in radius."
        await query.message.edit_text(txt)
        await state.clear()
        await query.answer()
        return

    await state.update_data(selected_ids=list(selected))
    await query.message.edit_reply_markup(
        reply_markup=get_theatres_selection_keyboard(theatres, selected, page=page)
    )
    await query.answer()
