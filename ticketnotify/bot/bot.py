"""Telegram bot setup, router registration, and dispatcher initialization."""

import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from ticketnotify.config import settings
from ticketnotify.adapters.registry import registry
from ticketnotify.engine.notifier import notifier
from ticketnotify.bot.handlers import (
    start_router,
    discovery_router,
    track_router,
    alerts_router,
    theatres_router,
    seats_router,
    location_router,
    settings_router,
    help_router,
    gdpr_router,
    admin_router,
)

logger = logging.getLogger(__name__)


def create_bot() -> Bot:
    return Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
    )


def create_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())

    # Register routers in priority order
    dp.include_router(start_router)
    dp.include_router(discovery_router)
    dp.include_router(track_router)
    dp.include_router(alerts_router)
    dp.include_router(theatres_router)
    dp.include_router(seats_router)
    dp.include_router(location_router)
    dp.include_router(settings_router)
    dp.include_router(help_router)
    dp.include_router(gdpr_router)
    dp.include_router(admin_router)

    return dp


async def init_bot_services(bot: Bot) -> None:
    """Links bot instance to notifier and registers admin alert callback."""
    notifier.set_bot(bot)
    await notifier.start()

    # Define scraper broken alert callback to Admin
    async def on_scraper_break(platform_name: str, message: str) -> None:
        try:
            alert_text = (
                f"🚨 *SCRAPER BROKEN ALERT*\n\n"
                f"Platform: *{platform_name.upper()}*\n"
                f"Detail: `{message}`\n\n"
                f"Circuit breaker tripped to OPEN. Monitoring paused on this platform to prevent blocking other platforms."
            )
            await bot.send_message(
                chat_id=settings.ADMIN_ID,
                text=alert_text,
                parse_mode="Markdown",
            )
        except Exception as err:
            logger.error(f"Failed to send scraper broken alert to admin: {err}")

    registry.set_admin_alert_callback(on_scraper_break)
