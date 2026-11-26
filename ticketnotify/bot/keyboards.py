"""Keyboards and inline buttons for TicketNotify bot."""

from typing import List, Dict, Set
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)

from ticketnotify.database.models import Alert


def get_language_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text="🇬🇧 English", callback_data="lang:en"),
            InlineKeyboardButton(text="🇮🇳 தமிழ் (Tamil)", callback_data="lang:ta"),
        ],
        [
            InlineKeyboardButton(text="🇮🇳 हिन्दी (Hindi)", callback_data="lang:hi"),
            InlineKeyboardButton(text="🇮🇳 తెలుగు (Telugu)", callback_data="lang:te"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_location_request_keyboard() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(text="📍 Share Current Location", request_location=True)],
        [KeyboardButton(text="❌ Cancel")],
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True, one_time_keyboard=True)


def get_movie_matches_keyboard(matches: List[dict]) -> InlineKeyboardMarkup:
    buttons = []
    for idx, m in enumerate(matches[:5]):
        text = f"🎬 {m['title']} ({', '.join(m.get('languages', [])[:2]) or 'All'})"
        buttons.append([InlineKeyboardButton(text=text, callback_data=f"sel_movie:{idx}")])
    buttons.append([InlineKeyboardButton(text="✏️ Re-type Movie Name", callback_data="retry_movie")])
    buttons.append([InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_flow")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_platform_selection_keyboard(
    supported_platforms: List[str],
    selected_platforms: Set[str],
) -> InlineKeyboardMarkup:
    platform_names = {
        "bms": "BookMyShow",
        "ticketnew": "Ticketnew",
        "district": "District (Zomato)",
        "pvrinox": "PVR INOX",
    }
    buttons = []
    for p in supported_platforms:
        name = platform_names.get(p, p.upper())
        check = "✅" if p in selected_platforms else "◻️"
        buttons.append([
            InlineKeyboardButton(
                text=f"{check} {name}",
                callback_data=f"toggle_plat:{p}"
            )
        ])

    buttons.append([
        InlineKeyboardButton(text="➡️ Continue with selected", callback_data="confirm_platforms")
    ])
    buttons.append([InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_flow")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_filter_builder_keyboard(current_filters: dict) -> InlineKeyboardMarkup:
    formats = current_filters.get("formats", [])
    has_imax = "IMAX" in [f.upper() for f in formats]
    has_3d = "3D" in [f.upper() for f in formats]
    has_4dx = "4DX" in [f.upper() for f in formats]

    buttons = [
        [
            InlineKeyboardButton(text=f"{'✅' if has_imax else '◻️'} IMAX", callback_data="toggle_filter:fmt_imax"),
            InlineKeyboardButton(text=f"{'✅' if has_3d else '◻️'} 3D", callback_data="toggle_filter:fmt_3d"),
            InlineKeyboardButton(text=f"{'✅' if has_4dx else '◻️'} 4DX", callback_data="toggle_filter:fmt_4dx"),
        ],
        [
            InlineKeyboardButton(text="🎯 All Formats (Default)", callback_data="toggle_filter:fmt_all"),
        ],
        [
            InlineKeyboardButton(text="💰 Max Price: " + (f"₹{current_filters.get('max_price')}" if current_filters.get('max_price') else "Any"), callback_data="set_max_price"),
            InlineKeyboardButton(text="🪑 Min Seats: " + str(current_filters.get('min_seats', 'Any')), callback_data="set_min_seats"),
        ],
        [
            InlineKeyboardButton(text="✅ Done / Confirm Tracking", callback_data="filters_done"),
        ],
        [InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_flow")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_theatres_selection_keyboard(
    theatres: List[Any],
    selected_ids: Set[str],
    page: int = 0,
    page_size: int = 5,
) -> InlineKeyboardMarkup:
    total = len(theatres)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = max(0, min(page, total_pages - 1))
    start_idx = page * page_size
    page_items = theatres[start_idx : start_idx + page_size]

    buttons = []
    # Theatre items
    for t in page_items:
        check = "✅" if t.canonical_id in selected_ids else "◻️"
        buttons.append([
            InlineKeyboardButton(
                text=f"{check} {t.display_label}",
                callback_data=f"th_tog:{t.canonical_id}:{page}",
            )
        ])

    # Pagination controls
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="⬅️ Prev", callback_data=f"th_page:{page - 1}"))
    nav_row.append(InlineKeyboardButton(text=f"📄 {page + 1}/{total_pages}", callback_data=f"th_page:{page}"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"th_page:{page + 1}"))
    if len(nav_row) > 1:
        buttons.append(nav_row)

    # Quick action presets
    buttons.append([
        InlineKeyboardButton(text="🔘 Select All", callback_data=f"th_act:all:{page}"),
        InlineKeyboardButton(text="📍 Nearest 5", callback_data=f"th_act:near5:{page}"),
    ])
    buttons.append([
        InlineKeyboardButton(text="🏢 Chains Only (PVR/INOX/Cinepolis)", callback_data=f"th_act:chains:{page}"),
    ])

    # Done / Continue
    count_str = f" ({len(selected_ids)} selected)" if selected_ids else " (All in radius)"
    buttons.append([
        InlineKeyboardButton(text=f"➡️ Continue{count_str}", callback_data=f"th_act:done:{page}")
    ])
    buttons.append([InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_flow")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_seat_preferences_keyboard(prefs: dict) -> InlineKeyboardMarkup:
    needed = prefs.get("seats_needed", 1)
    consec = "Yes" if prefs.get("must_be_consecutive", True) else "No"
    row = prefs.get("row_zone", "any").title()
    col = prefs.get("column_zone", "any").title()
    cat = prefs.get("seat_category", "any").title()

    buttons = [
        [
            InlineKeyboardButton(text=f"💺 Seats: {needed}", callback_data="seat_cycle_needed"),
            InlineKeyboardButton(text=f"🔗 Consecutive: {consec}", callback_data="seat_toggle_consec"),
        ],
        [
            InlineKeyboardButton(text=f"↕️ Row: {row}", callback_data="seat_cycle_row"),
            InlineKeyboardButton(text=f"↔️ Column: {col}", callback_data="seat_cycle_col"),
        ],
        [
            InlineKeyboardButton(text=f"🏷 Category: {cat}", callback_data="seat_cycle_cat"),
        ],
        [
            InlineKeyboardButton(text="➡️ Continue to Alert Urgency", callback_data="seat_prefs_done"),
        ],
        [InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_flow")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_urgency_keyboard(selected_urgency: str = "WARM") -> InlineKeyboardMarkup:
    u = selected_urgency.upper()
    buttons = [
        [
            InlineKeyboardButton(
                text=f"{'✅' if u == 'HOT' else '◻️'} 🔥 Hot (1-3s polling)",
                callback_data="urg_set:HOT",
            )
        ],
        [
            InlineKeyboardButton(
                text=f"{'✅' if u == 'WARM' else '◻️'} ⚡ Normal (10-15s polling)",
                callback_data="urg_set:WARM",
            )
        ],
        [
            InlineKeyboardButton(
                text=f"{'✅' if u == 'COLD' else '◻️'} 💤 Passive (1-2 min polling)",
                callback_data="urg_set:COLD",
            )
        ],
        [InlineKeyboardButton(text="✅ Finalize Alert", callback_data="urg_confirm")],
        [InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_flow")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_alert_item_keyboard(alert: Alert) -> InlineKeyboardMarkup:
    status_button = (
        InlineKeyboardButton(text="▶️ Resume", callback_data=f"resume_alert:{alert.id}")
        if alert.status == "paused"
        else InlineKeyboardButton(text="⏸ Pause", callback_data=f"pause_alert:{alert.id}")
    )
    mute_button = (
        InlineKeyboardButton(text="🔔 Unmute", callback_data=f"unmute:{alert.id}")
        if alert.is_muted
        else InlineKeyboardButton(text="🔕 Mute", callback_data=f"mute:{alert.id}")
    )

    buttons = [
        [status_button, mute_button],
        [
            InlineKeyboardButton(text="🏛 Theatres", callback_data=f"edit_theatres:{alert.id}"),
            InlineKeyboardButton(text="💺 Seats", callback_data=f"edit_seats:{alert.id}"),
        ],
        [InlineKeyboardButton(text="🗑 Delete Alert", callback_data=f"delete_alert:{alert.id}")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Persistent main menu reply keyboard."""
    keyboard = [
        [KeyboardButton(text="🎬 Now Showing"), KeyboardButton(text="🗓 Coming Soon")],
        [KeyboardButton(text="🔔 My Alerts"), KeyboardButton(text="🏛 Theatres")],
        [KeyboardButton(text="💺 Seat Preferences"), KeyboardButton(text="⚙️ Settings")],
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


def get_discovery_card_keyboard(movie_title: str, is_now_showing: bool = False) -> InlineKeyboardMarkup:
    """Action buttons for Now Showing and Coming Soon cards."""
    # Sanitize title for callback payload
    safe_title = movie_title[:25].strip()
    buttons = [
        [
            InlineKeyboardButton(
                text="🚨 Alert when bookings open",
                callback_data=f"disc_open:{safe_title}",
            )
        ],
        [
            InlineKeyboardButton(
                text="📊 Track current shows",
                callback_data=f"disc_track:{safe_title}",
            ),
            InlineKeyboardButton(
                text="ℹ️ Details",
                callback_data=f"disc_info:{safe_title}",
            ),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_settings_keyboard(user) -> InlineKeyboardMarkup:
    qh_status = "🟢 Enabled" if user.quiet_hours_enabled else "🔴 Disabled"
    buttons = [
        [InlineKeyboardButton(text=f"🌙 Quiet Hours ({qh_status})", callback_data="toggle_quiet_hours")],
        [InlineKeyboardButton(text=f"⏰ Set Quiet Time ({user.quiet_hours_start}:00 - {user.quiet_hours_end}:00)", callback_data="config_quiet_time")],
        [InlineKeyboardButton(text=f"🌐 Change Language ({user.language.upper()})", callback_data="change_language")],
        [InlineKeyboardButton(text="🗑 Delete My Account (GDPR)", callback_data="gdpr_delete")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)
