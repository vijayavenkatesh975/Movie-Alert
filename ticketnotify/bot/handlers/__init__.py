"""Bot handlers package."""

from ticketnotify.bot.handlers.start import router as start_router
from ticketnotify.bot.handlers.discovery import router as discovery_router
from ticketnotify.bot.handlers.track import router as track_router
from ticketnotify.bot.handlers.alerts import router as alerts_router
from ticketnotify.bot.handlers.theatres import router as theatres_router
from ticketnotify.bot.handlers.seats import router as seats_router
from ticketnotify.bot.handlers.location import router as location_router
from ticketnotify.bot.handlers.settings import router as settings_router
from ticketnotify.bot.handlers.help import router as help_router
from ticketnotify.bot.handlers.gdpr import router as gdpr_router
from ticketnotify.bot.handlers.admin import router as admin_router

__all__ = [
    "start_router",
    "discovery_router",
    "track_router",
    "alerts_router",
    "theatres_router",
    "seats_router",
    "location_router",
    "settings_router",
    "help_router",
    "gdpr_router",
    "admin_router",
]
