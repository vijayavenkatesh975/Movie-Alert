"""/start and first-time guided onboarding flow."""

import logging
from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    Message,
    CallbackQuery,
    ReplyKeyboardRemove,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from sqlalchemy import update

from ticketnotify.database.session import get_db_session
from ticketnotify.database.crud import (
    get_or_create_user,
    update_user_language,
    create_location,
    get_default_location,
    update_user_selected_theatres,
)
from ticketnotify.database.models import User
from ticketnotify.bot.keyboards import (
    get_language_keyboard,
    get_main_menu_keyboard,
    get_theatres_selection_keyboard,
)
from ticketnotify.bot.states import StartFlow
from ticketnotify.location import geocoder, map_location_to_platforms
from ticketnotify.location.theatre_merger import get_theatres_for_location, MergedCinema
from ticketnotify.location.models import NormalizedLocation
from ticketnotify.bot.locales import get_text

logger = logging.getLogger(__name__)
router = Router(name="start_router")

TOP_CITIES = [
    ("Chennai", "chennai"),
    ("Bengaluru", "bengaluru"),
    ("Mumbai", "mumbai"),
    ("Delhi NCR", "delhi"),
    ("Hyderabad", "hyderabad"),
    ("Kolkata", "kolkata"),
]


def get_city_quick_keyboard() -> InlineKeyboardMarkup:
    """Quick selection inline keyboard for major cinema cities."""
    buttons = []
    row = []
    for label, code in TOP_CITIES:
        row.append(InlineKeyboardButton(text=f"🏛 {label}", callback_data=f"sel_city:{code}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_onboarding_location_keyboard() -> ReplyKeyboardMarkup:
    """Reply keyboard offering GPS share or text-only skip."""
    buttons = [
        [KeyboardButton(text="📍 Share GPS Location (Optional)", request_location=True)],
        [KeyboardButton(text="⏩ Skip Location (Use City Center)")],
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True, one_time_keyboard=True)


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
        if not user.is_active:
            await session.execute(
                update(User).where(User.id == user.id).values(is_active=True)
            )

    command_args = (message.text or "").split(maxsplit=1)
    deep_link_movie = None
    if len(command_args) > 1 and command_args[1].startswith("track_"):
        import urllib.parse
        raw_slug = command_args[1][6:]
        deep_link_movie = urllib.parse.unquote_plus(raw_slug)

    if deep_link_movie and not created:
        # User already onboarded, directly initialize track flow for this shared movie
        await message.answer(
            f"🎬 *Shared Movie Alert Link Activated!*\n\n"
            f"Ready to track tickets for: *{deep_link_movie}*\n"
            f"Type /track or send location to monitor ticket release.",
            parse_mode="Markdown",
            reply_markup=get_main_menu_keyboard(),
        )
        return

    welcome_title = get_text("welcome", user.language)
    intro_text = get_text("intro", user.language)
    step1_title = get_text("select_lang", user.language)

    text = (
        f"{welcome_title}\n\n"
        f"{intro_text}\n\n"
        f"{step1_title}"
    )

    await message.answer(
        text,
        parse_mode="Markdown",
        reply_markup=get_language_keyboard(),
    )
    await state.set_state(StartFlow.choosing_language)


@router.callback_query(F.data.startswith("lang:"))
async def handle_lang_callback(query: CallbackQuery, state: FSMContext):
    lang_code = query.data.split(":")[1]
    async with get_db_session() as session:
        user, _ = await get_or_create_user(session, query.from_user.id)
        await update_user_language(session, user.id, lang_code)

    lang_names = {
        "en": "English",
        "ta": "தமிழ் (Tamil)",
        "hi": "हिन्दी (Hindi)",
        "te": "తెలుగు (Telugu)",
        "kn": "ಕನ್ನಡ (Kannada)",
    }
    chosen_lang = lang_names.get(lang_code, "English")

    await query.message.edit_text(
        f"✅ Language set to *{chosen_lang}*!\n\n"
        "📍 *Step 2: Choose your cinema city:*\n"
        "Tap your city below or type any city name in India (e.g. `Chennai`, `Bengaluru`, `Coimbatore`):",
        parse_mode="Markdown",
        reply_markup=get_city_quick_keyboard(),
    )
    await state.set_state(StartFlow.choosing_city)
    await query.answer()


@router.callback_query(StartFlow.choosing_city, F.data.startswith("sel_city:"))
async def handle_city_quick_select(query: CallbackQuery, state: FSMContext):
    city_code = query.data.split(":")[1]
    city_names = {
        "chennai": "Chennai",
        "bengaluru": "Bengaluru",
        "mumbai": "Mumbai",
        "delhi": "Delhi",
        "hyderabad": "Hyderabad",
        "kolkata": "Kolkata",
    }
    city_name = city_names.get(city_code, city_code.title())

    # Geocode city
    norm_loc = await geocoder.geocode(f"{city_name}, India")
    if not norm_loc:
        norm_loc = NormalizedLocation(
            raw_query=city_name,
            city=city_name,
            country="India",
            country_code="in",
            latitude=13.0827 if city_name == "Chennai" else 12.9716,
            longitude=80.2707 if city_name == "Chennai" else 77.5946,
            display_name=f"{city_name}, India",
        )

    await proceed_to_theatre_onboarding(query.message, state, norm_loc, is_callback=True)
    await query.answer()


@router.message(StartFlow.choosing_city, F.text)
async def handle_city_text_input(message: Message, state: FSMContext):
    q = message.text.strip()
    wait_msg = await message.answer(f"🔍 Finding '{q}'...", reply_markup=ReplyKeyboardRemove())
    norm_loc = await geocoder.geocode(q)

    if not norm_loc:
        await wait_msg.edit_text(f"❌ Could not resolve '{q}'. Please select your city below:", reply_markup=get_city_quick_keyboard())
        return

    await wait_msg.delete()
    await proceed_to_theatre_onboarding(message, state, norm_loc, is_callback=False)


async def proceed_to_theatre_onboarding(target: Message, state: FSMContext, norm_loc, is_callback: bool = False):
    """Saves city location and displays complete city-wide theatre count."""
    async with get_db_session() as session:
        user, _ = await get_or_create_user(session, target.chat.id)
        loc = await create_location(
            session=session,
            user_id=user.id,
            name=norm_loc.label or f"{norm_loc.city}, {norm_loc.country}",
            normalized_city=norm_loc.city,
            normalized_country=norm_loc.country,
            country_code=norm_loc.country_code,
            latitude=norm_loc.latitude,
            longitude=norm_loc.longitude,
            platform_mappings=norm_loc.platform_codes,
            is_default=True,
        )

    # Retrieve all theatres in chosen city without radius limits
    theatres = await get_theatres_for_location(location=norm_loc, radius_km=None)

    await state.update_data(
        onboarding_city=norm_loc.city,
        theatres_list=[t.dict() for t in theatres],
        selected_theatres=[],
        location_id=loc.id,
    )

    text = (
        f"📍 *City Confirmed: {norm_loc.city}, {norm_loc.country}*\n\n"
        f"Found *{len(theatres)} available theatres* across BookMyShow, PVR INOX, District, and Ticketnew!\n\n"
        "🏛 *Step 3: Choose Your Preferred Theatres*\n"
        "You can pick your favourite cinemas now, or monitor all theatres across the entire city:"
    )

    buttons = [
        [
            InlineKeyboardButton(text="🔘 Monitor All Theatres in City", callback_data="ob_th:all"),
        ],
        [
            InlineKeyboardButton(text="🏛 Choose Specific Theatres", callback_data="ob_th:pick"),
        ],
        [
            InlineKeyboardButton(text="⏩ Skip for Now", callback_data="ob_th:skip"),
        ],
    ]

    markup = InlineKeyboardMarkup(inline_keyboard=buttons)
    if is_callback:
        await target.edit_text(text, parse_mode="Markdown", reply_markup=markup)
    else:
        await target.answer(text, parse_mode="Markdown", reply_markup=markup)

    await state.set_state(StartFlow.selecting_default_theatres)


@router.callback_query(StartFlow.selecting_default_theatres, F.data == "ob_th:all")
@router.callback_query(StartFlow.selecting_default_theatres, F.data == "ob_th:skip")
async def on_onboarding_theatres_all(query: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    city_name = data.get("onboarding_city", "Chennai")

    # Persist empty or all in default theatres
    save_dict = {
        "city": city_name,
        "canonical_ids": [],
        "names": [],
    }
    async with get_db_session() as session:
        user, _ = await get_or_create_user(session, query.from_user.id)
        await update_user_selected_theatres(session, user.id, save_dict)

    await finish_onboarding(query.message, state, city_name, is_callback=True)
    await query.answer()


@router.callback_query(StartFlow.selecting_default_theatres, F.data == "ob_th:pick")
async def on_onboarding_theatres_pick(query: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    theatres_dicts = data.get("theatres_list", [])
    theatres = [MergedCinema(**d) for d in theatres_dicts]
    city_name = data.get("onboarding_city", "Chennai")

    markup = get_theatres_selection_keyboard(
        theatres=theatres,
        selected_ids=set(),
        page=0,
        page_size=5,
    )

    await query.message.edit_text(
        f"🏛 *Select Preferred Theatres in {city_name}:*\n"
        "Tap the theatres you visit most often, then tap *Confirm Selection* below:",
        parse_mode="Markdown",
        reply_markup=markup,
    )
    # Transition to theatres router selection state
    from ticketnotify.bot.states import TheatresFlow
    await state.set_state(TheatresFlow.selecting_theatres)
    await state.update_data(
        edit_alert_id=None,
        city_name=city_name,
        raw_theatres=theatres_dicts,
        selected_ids=[],
        filter_locality="all",
        filter_chain="all",
        search_query="",
        sort_by="alpha",
        page=0,
    )
    await query.answer()


async def finish_onboarding(target: Message, state: FSMContext, city_name: str, is_callback: bool = False):
    await state.clear()
    text = (
        f"🎉 *Setup Complete! Welcome aboard.*\n\n"
        f"📍 Selected City: *{city_name}*\n"
        "📡 Connected Platforms: *BookMyShow*, *PVR INOX*, *District*, *Ticketnew*\n\n"
        "🎬 *How to set your first alert:*\n"
        "• Tap **🎬 Now Showing** or **🗓 Coming Soon** below to pick a movie.\n"
        "• Or send `/track <movie title>` (e.g. `/track Toxic`, `/track Avatar`).\n"
        "• We will immediately alert you when advance bookings open or prices drop!"
    )

    markup = get_main_menu_keyboard()
    if is_callback:
        await target.delete()
        await target.answer(text, parse_mode="Markdown", reply_markup=markup)
    else:
        await target.answer(text, parse_mode="Markdown", reply_markup=markup)
