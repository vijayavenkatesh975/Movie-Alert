"""Keyboards and inline buttons for TicketNotify bot."""
from __future__ import annotations

from typing import List, Dict, Set, Any, Optional
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
        [
            InlineKeyboardButton(text="🇮🇳 ಕನ್ನಡ (Kannada)", callback_data="lang:kn"),
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
    has_2d = "2D" in [f.upper() for f in formats]
    has_imax = "IMAX" in [f.upper() for f in formats]
    has_3d = "3D" in [f.upper() for f in formats]
    has_4dx = "4DX" in [f.upper() for f in formats]

    languages = current_filters.get("languages", [])
    has_tam = "TAMIL" in [l.upper() for l in languages]
    has_eng = "ENGLISH" in [l.upper() for l in languages]
    has_hin = "HINDI" in [l.upper() for l in languages]
    has_tel = "TELUGU" in [l.upper() for l in languages]

    date_win = (current_filters.get("date_window") or "any").title()
    time_win = (current_filters.get("time_slot") or "any").title()

    buttons = [
        # Formats
        [
            InlineKeyboardButton(text=f"{'✅' if has_2d else '◻️'} 2D", callback_data="toggle_filter:fmt_2d"),
            InlineKeyboardButton(text=f"{'✅' if has_imax else '◻️'} IMAX", callback_data="toggle_filter:fmt_imax"),
            InlineKeyboardButton(text=f"{'✅' if has_3d else '◻️'} 3D", callback_data="toggle_filter:fmt_3d"),
            InlineKeyboardButton(text=f"{'✅' if has_4dx else '◻️'} 4DX", callback_data="toggle_filter:fmt_4dx"),
        ],
        # Languages
        [
            InlineKeyboardButton(text=f"{'✅' if has_tam else '◻️'} Tamil", callback_data="toggle_filter:lang_tamil"),
            InlineKeyboardButton(text=f"{'✅' if has_eng else '◻️'} English", callback_data="toggle_filter:lang_eng"),
            InlineKeyboardButton(text=f"{'✅' if has_hin else '◻️'} Hindi", callback_data="toggle_filter:lang_hindi"),
            InlineKeyboardButton(text=f"{'✅' if has_tel else '◻️'} Telugu", callback_data="toggle_filter:lang_telugu"),
        ],
        # Date & Time window
        [
            InlineKeyboardButton(text=f"📅 Date: {date_win}", callback_data="toggle_filter:cycle_date"),
            InlineKeyboardButton(text=f"🕒 Time: {time_win}", callback_data="toggle_filter:cycle_time"),
        ],
        [
            InlineKeyboardButton(text="🎯 All Filters Reset", callback_data="toggle_filter:fmt_all"),
        ],
        [
            InlineKeyboardButton(text="✅ Done / Continue to Seats", callback_data="filters_done"),
        ],
        [InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_flow")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_theatres_selection_keyboard(
    theatres: List[Any],
    selected_ids: Set[str],
    page: int = 0,
    page_size: int = 5,
    current_locality: Optional[str] = None,
    current_chain: Optional[str] = None,
    sort_by: str = "alpha",
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
    nav_row.append(InlineKeyboardButton(text=f"📄 {page + 1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"th_page:{page + 1}"))
    if len(nav_row) > 1:
        buttons.append(nav_row)

    # Bulk toggles: Select All & Clear All
    buttons.append([
        InlineKeyboardButton(text="🔘 Select All", callback_data=f"th_act:all:{page}"),
        InlineKeyboardButton(text="🧹 Clear All", callback_data=f"th_act:clear:{page}"),
    ])

    # Filter & Sort controls
    loc_label = f"📍 Locality ({current_locality[:8]}..)" if current_locality and current_locality != "all" else "📍 Filter Locality"
    chain_label = f"🏢 Chain ({current_chain})" if current_chain and current_chain != "all" else "🏢 Filter Chain"
    buttons.append([
        InlineKeyboardButton(text=loc_label, callback_data=f"th_act:filt_loc:{page}"),
        InlineKeyboardButton(text=chain_label, callback_data=f"th_act:filt_chain:{page}"),
    ])

    sort_label = "📏 Sort: Dist" if sort_by == "alpha" else "🔤 Sort: A-Z"
    next_sort = "distance" if sort_by == "alpha" else "alpha"
    buttons.append([
        InlineKeyboardButton(text=sort_label, callback_data=f"th_act:sort_{next_sort}:{page}"),
        InlineKeyboardButton(text="🔍 Search Name/Mall", callback_data=f"th_act:search:{page}"),
    ])

    # Refresh from platforms
    buttons.append([
        InlineKeyboardButton(text="🔄 Refresh Theatres Live", callback_data=f"th_act:refresh:{page}"),
    ])

    # Done / Confirm
    count_str = f" ({len(selected_ids)} Selected)" if selected_ids else " (All Theatres in City)"
    buttons.append([
        InlineKeyboardButton(text=f"✅ Confirm Selection{count_str}", callback_data=f"th_act:done:{page}")
    ])
    buttons.append([InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_flow")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_locality_filter_keyboard(localities: List[str], current_loc: Optional[str] = None) -> InlineKeyboardMarkup:
    """Inline keyboard for filtering theatres by locality."""
    buttons = []
    buttons.append([InlineKeyboardButton(text="🌟 All Localities (Show All)", callback_data="th_setloc:all")])
    # 2 buttons per row
    row = []
    for loc in localities:
        prefix = "👉 " if current_loc and current_loc.lower() == loc.lower() else ""
        row.append(InlineKeyboardButton(text=f"{prefix}{loc}", callback_data=f"th_setloc:{loc}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="⬅️ Back to Theatres", callback_data="th_act:back:0")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_chain_filter_keyboard(chains: List[str], current_chain: Optional[str] = None) -> InlineKeyboardMarkup:
    """Inline keyboard for filtering theatres by cinema chain."""
    buttons = []
    buttons.append([InlineKeyboardButton(text="🌟 All Chains (Show All)", callback_data="th_setchain:all")])
    row = []
    for ch in chains:
        prefix = "👉 " if current_chain and current_chain.lower() == ch.lower() else ""
        row.append(InlineKeyboardButton(text=f"{prefix}{ch}", callback_data=f"th_setchain:{ch}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="⬅️ Back to Theatres", callback_data="th_act:back:0")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_seat_preferences_keyboard(prefs: dict) -> InlineKeyboardMarkup:
    needed = prefs.get("seats_needed", 1)
    consec = "Yes" if prefs.get("must_be_consecutive", True) else "No"
    row = prefs.get("row_zone", "any").title()
    col = prefs.get("column_zone", "any").title()
    cat = prefs.get("seat_category", "any").title()
    mode = prefs.get("seat_mode", "zone").title()

    buttons = [
        [
            InlineKeyboardButton(text=f"⚙️ Mode: {mode} Mode", callback_data="seat_toggle_mode"),
        ],
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


def get_discovery_catalog_keyboard(
    category: str,
    page: int,
    total_pages: int,
    movies: List[dict],
) -> InlineKeyboardMarkup:
    """Navigation and quick action keyboard for paginated movie discovery."""
    buttons = []
    # 1. Action buttons for movies on the current page
    for m in movies:
        safe_title = m["title"][:18].strip()
        buttons.append([
            InlineKeyboardButton(
                text=f"🚨 Alert '{safe_title}'",
                callback_data=f"disc_open:{m['title'][:25]}",
            ),
            InlineKeyboardButton(
                text="ℹ️ Details",
                callback_data=f"disc_det:{m['title'][:25]}",
            ),
        ])

    # 2. Pagination controls
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="◀️ Prev", callback_data=f"disc_p:{category}:{page - 1}"))
    nav_row.append(InlineKeyboardButton(text=f"📄 {page + 1}/{max(1, total_pages)}", callback_data="noop"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton(text="Next ▶️", callback_data=f"disc_p:{category}:{page + 1}"))
    if len(nav_row) > 1:
        buttons.append(nav_row)

    # 3. Category Switchers
    cat_row1 = [
        InlineKeyboardButton(
            text="🎬 Now Showing" if category != "now_showing" else "👉 🎬 Now Showing",
            callback_data="disc_cat:now_showing",
        ),
        InlineKeyboardButton(
            text="🗓 Coming Soon" if category != "coming_soon" else "👉 🗓 Coming Soon",
            callback_data="disc_cat:coming_soon",
        ),
    ]
    cat_row2 = [
        InlineKeyboardButton(
            text="⚡ This Week" if category != "this_week" else "👉 ⚡ This Week",
            callback_data="disc_cat:this_week",
        ),
        InlineKeyboardButton(
            text="📅 This Month" if category != "this_month" else "👉 📅 This Month",
            callback_data="disc_cat:this_month",
        ),
    ]
    cat_row3 = [
        InlineKeyboardButton(
            text="🎞 Recent" if category != "recent" else "👉 🎞 Recent",
            callback_data="disc_cat:recent",
        ),
        InlineKeyboardButton(
            text="🔍 Search" if category != "search" else "👉 🔍 Search",
            callback_data="disc_cat:search",
        ),
    ]
    buttons.append(cat_row1)
    buttons.append(cat_row2)
    buttons.append(cat_row3)
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_settings_keyboard(user) -> InlineKeyboardMarkup:
    qh_status = "🟢 Enabled" if user.quiet_hours_enabled else "🔴 Disabled"
    pause_label = "▶️ Resume Alerts" if getattr(user, "alerts_paused", False) else "⏸ Pause All Alerts"
    pause_cb = "resume_all_alerts" if getattr(user, "alerts_paused", False) else "pause_all_alerts"

    snoozed = getattr(user, "snoozed_until", None)
    snooze_label = "💤 Snoozed (Tap to manage)" if snoozed else "💤 Snooze Notifications"

    buttons = [
        [InlineKeyboardButton(text="🔔 Customise Alert Triggers", callback_data="manage_notif_prefs")],
        [
            InlineKeyboardButton(text=pause_label, callback_data=pause_cb),
            InlineKeyboardButton(text=snooze_label, callback_data="manage_snooze"),
        ],
        [
            InlineKeyboardButton(text=f"🌙 Quiet Hours ({qh_status})", callback_data="toggle_quiet_hours"),
            InlineKeyboardButton(text=f"⏰ Set Times ({user.quiet_hours_start}:00-{user.quiet_hours_end}:00)", callback_data="config_quiet_time"),
        ],
        [InlineKeyboardButton(text=f"🌐 Change Language ({user.language.upper()})", callback_data="change_language")],
        [InlineKeyboardButton(text="🗑 Delete My Account (GDPR)", callback_data="gdpr_delete")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_notification_settings_keyboard(prefs: Dict[str, bool]) -> InlineKeyboardMarkup:
    """Toggle keyboard for individual notification types."""
    # Available triggers
    triggers = [
        ("bookings_opened", "🚨 Bookings Opened"),
        ("new_show_added", "✨ New Shows Added"),
        ("price_drop", "📉 Price Drops"),
        ("preferred_seats_available", "💺 Preferred Seats Available"),
        ("seats_filling_fast", "⚡ Filling-Fast Shows"),
        ("release_date_change", "🗓 Release-Date Changes"),
    ]
    buttons = []
    for key, label in triggers:
        is_on = prefs.get(key, True)  # Enabled by default
        check = "✅" if is_on else "◻️"
        buttons.append([
            InlineKeyboardButton(
                text=f"{check} {label}",
                callback_data=f"tog_notif:{key}",
            )
        ])
    buttons.append([InlineKeyboardButton(text="⬅️ Back to Settings", callback_data="back_to_settings")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_snooze_keyboard() -> InlineKeyboardMarkup:
    """Keyboard for selecting snooze durations."""
    buttons = [
        [
            InlineKeyboardButton(text="⏱ 1 Hour", callback_data="set_snooze:1"),
            InlineKeyboardButton(text="⏱ 4 Hours", callback_data="set_snooze:4"),
        ],
        [
            InlineKeyboardButton(text="🌙 24 Hours", callback_data="set_snooze:24"),
            InlineKeyboardButton(text="🔔 Turn Off Snooze", callback_data="set_snooze:0"),
        ],
        [InlineKeyboardButton(text="⬅️ Back to Settings", callback_data="back_to_settings")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)
