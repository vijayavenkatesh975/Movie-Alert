"""FSM States for aiogram 3 dialogs."""

from aiogram.fsm.state import State, StatesGroup


class StartFlow(StatesGroup):
    choosing_language = State()
    choosing_city = State()
    waiting_for_location = State()
    selecting_default_theatres = State()


class TrackFlow(StatesGroup):
    waiting_for_movie_title = State()
    selecting_movie_match = State()
    waiting_for_location = State()
    selecting_platforms = State()
    selecting_theatres = State()
    configuring_filters = State()
    configuring_seats = State()
    selecting_urgency = State()
    confirm_alert = State()


class TheatresFlow(StatesGroup):
    choosing_scope = State()
    choosing_alert = State()
    selecting_theatres = State()
    filtering_locality = State()
    searching_theatre = State()


class SeatsFlow(StatesGroup):
    choosing_alert = State()
    configuring_seats = State()


class LocationFlow(StatesGroup):
    waiting_for_location = State()


class SettingsFlow(StatesGroup):
    choosing_option = State()
    setting_quiet_hours = State()
    configuring_notifications = State()


class DiscoveryFlow(StatesGroup):
    browsing = State()
    searching = State()


class AdminFlow(StatesGroup):
    waiting_for_broadcast = State()
