"""Outbound Telegram notification engine with priority send path, rate limiting, and metrics."""

import asyncio
import logging
import time
from datetime import datetime
from typing import Optional, Dict, Any
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramRetryAfter, TelegramAPIError
from sqlalchemy import update

from ticketnotify.config import settings
from ticketnotify.adapters.base import Show
from ticketnotify.database.models import Alert, User
from ticketnotify.database.crud import log_notification_sent, is_notification_duplicate
from ticketnotify.database.session import get_db_session

logger = logging.getLogger(__name__)


class QueuedNotification:
    def __init__(
        self,
        alert_id: int,
        user_id: int,
        chat_id: int,
        user_obj: Optional[User],
        platform: str,
        notification_type: str,
        show: Show,
        payload_hash: str,
        summary: str,
        seat_recommendation: Optional[str] = None,
        is_priority: bool = False,
    ):
        self.alert_id = alert_id
        self.user_id = user_id
        self.chat_id = chat_id
        self.user_obj = user_obj
        self.platform = platform
        self.notification_type = notification_type
        self.show = show
        self.payload_hash = payload_hash
        self.summary = summary
        self.seat_recommendation = seat_recommendation
        self.is_priority = is_priority
        self.created_at = time.time()


class TelegramNotifier:
    def __init__(self, bot: Optional[Bot] = None):
        self.bot = bot
        self._queue: asyncio.Queue[QueuedNotification] = asyncio.Queue()
        self._last_chat_send_time: Dict[int, float] = {}
        self._global_send_times: list[float] = []
        self._worker_task: Optional[asyncio.Task] = None
        self._running = False
        self.metrics = {
            "total_sent": 0,
            "total_failed": 0,
            "priority_sent": 0,
            "latencies_seconds": [],
        }

    def set_bot(self, bot: Bot) -> None:
        self.bot = bot

    async def start(self) -> None:
        """Starts the outbound rate-limited sender worker."""
        if self._running:
            return
        self._running = True
        self._worker_task = asyncio.create_task(self._process_queue())
        logger.info("Telegram outbound notification worker started.")

    async def stop(self) -> None:
        """Stops the sender worker."""
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        logger.info("Telegram outbound notification worker stopped.")

    async def enqueue(
        self,
        alert: Alert,
        platform: str,
        notification_type: str,
        show: Show,
        payload_hash: str,
        summary: str,
        seat_recommendation: Optional[str] = None,
    ) -> bool:
        """Enqueues or fast-paths notification."""
        chat_id = alert.user.telegram_id if alert.user else None
        if not chat_id:
            return False

        # Database deduplication check
        async with get_db_session() as session:
            is_dup = await is_notification_duplicate(session, alert.id, platform, payload_hash)
            if is_dup:
                logger.debug(f"Skipping duplicate notification for alert {alert.id}, hash {payload_hash}")
                return False

        is_priority = (notification_type == "bookings_opened")
        item = QueuedNotification(
            alert_id=alert.id,
            user_id=alert.user_id,
            chat_id=chat_id,
            user_obj=alert.user,
            platform=platform,
            notification_type=notification_type,
            show=show,
            payload_hash=payload_hash,
            summary=summary,
            seat_recommendation=seat_recommendation,
            is_priority=is_priority,
        )

        # Fast-path for high priority booking openings
        if is_priority and self.bot:
            success = await self._send_item_direct(item)
            if success:
                self.metrics["priority_sent"] += 1
                return True

        await self._queue.put(item)
        return True

    def _is_quiet_hours(self, user: Optional[User]) -> bool:
        """Check if user has quiet hours active right now."""
        if not user or not user.quiet_hours_enabled:
            return False
        current_hour = datetime.utcnow().hour
        start = user.quiet_hours_start
        end = user.quiet_hours_end

        if start > end:
            return current_hour >= start or current_hour < end
        else:
            return start <= current_hour < end

    def format_message(self, item: QueuedNotification) -> tuple[str, InlineKeyboardMarkup]:
        """Formats the notification according to specification."""
        show = item.show
        platform_labels = {
            "bms": "BookMyShow",
            "ticketnew": "Ticketnew",
            "district": "District (by Zomato)",
            "pvrinox": "PVR INOX",
        }
        platform_display = platform_labels.get(item.platform.lower(), item.platform.upper())

        alert_titles = {
            "bookings_opened": "🚨 *BOOKINGS OPENED*",
            "new_show_added": "✨ *NEW SHOW ADDED*",
            "seats_filling_fast": "⚡ *SEATS FILLING FAST*",
            "price_drop": "📉 *PRICE DROP*",
            "specific_cinema_opened": "🏛 *CINEMA OPENED*",
        }
        badge = alert_titles.get(item.notification_type, "🎬 *MOVIE ALERT*")

        seats_line = f"💺 {show.seat_status_display} | {show.price_display}"
        seat_rec_line = f"\n🎯 *Recommended:* {item.seat_recommendation}" if item.seat_recommendation else ""

        text = (
            f"{badge}\n\n"
            f"🎬 *{show.movie_title}* ({show.language}, {show.format})\n"
            f"📍 {show.cinema_name}\n"
            f"🕒 {show.date} | {show.time}\n"
            f"{seats_line}"
            f"{seat_rec_line}\n"
            f"🏷 Platform: *{platform_display}*"
        )

        buttons = [
            [InlineKeyboardButton(text="🎟 Book Now", url=show.booking_url)],
            [
                InlineKeyboardButton(text="🔕 Mute Alert", callback_data=f"mute:{item.alert_id}"),
                InlineKeyboardButton(text="🛑 Stop Tracking", callback_data=f"stop:{item.alert_id}"),
            ],
        ]
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        return text, keyboard

    async def _send_item_direct(self, item: QueuedNotification) -> bool:
        """Attempts an immediate rate-checked direct transmission."""
        now = time.time()
        last_chat_time = self._last_chat_send_time.get(item.chat_id, 0.0)
        if now - last_chat_time < settings.CHAT_RATE_LIMIT_PER_SEC:
            return False  # Fall back to queue to honor chat rate limit

        try:
            text, keyboard = self.format_message(item)
            await self.bot.send_message(
                chat_id=item.chat_id,
                text=text,
                parse_mode="Markdown",
                reply_markup=keyboard,
                disable_web_page_preview=False,
            )
            self._last_chat_send_time[item.chat_id] = time.time()
            self._global_send_times.append(time.time())
            latency = time.time() - item.created_at
            self.metrics["latencies_seconds"].append(latency)
            self.metrics["total_sent"] += 1

            async with get_db_session() as session:
                await log_notification_sent(
                    session=session,
                    alert_id=item.alert_id,
                    user_id=item.user_id,
                    platform=item.platform,
                    notification_type=item.notification_type,
                    payload_hash=item.payload_hash,
                    show_key=item.show.show_id,
                    message_text=text,
                )
            return True
        except Exception:
            return False

    async def _process_queue(self) -> None:
        """Worker loop processing notifications with rate limits."""
        while self._running:
            try:
                item = await self._queue.get()

                # Check quiet hours
                if self._is_quiet_hours(item.user_obj) and item.notification_type != "bookings_opened":
                    logger.info(f"Notification delayed due to quiet hours for user {item.chat_id}")
                    await asyncio.sleep(60)
                    await self._queue.put(item)
                    self._queue.task_done()
                    continue

                # Rate limiting: 1 msg/sec per chat
                now = time.time()
                last_chat_time = self._last_chat_send_time.get(item.chat_id, 0.0)
                if now - last_chat_time < settings.CHAT_RATE_LIMIT_PER_SEC:
                    wait_time = settings.CHAT_RATE_LIMIT_PER_SEC - (now - last_chat_time)
                    await asyncio.sleep(wait_time)

                # Rate limiting: 30 msgs/sec global limit
                now = time.time()
                self._global_send_times = [t for t in self._global_send_times if now - t < 1.0]
                if len(self._global_send_times) >= settings.GLOBAL_RATE_LIMIT_PER_SEC:
                    await asyncio.sleep(0.05)

                if self.bot:
                    text, keyboard = self.format_message(item)
                    try:
                        await self.bot.send_message(
                            chat_id=item.chat_id,
                            text=text,
                            parse_mode="Markdown",
                            reply_markup=keyboard,
                            disable_web_page_preview=False,
                        )
                        self._last_chat_send_time[item.chat_id] = time.time()
                        self._global_send_times.append(time.time())
                        latency = time.time() - item.created_at
                        self.metrics["latencies_seconds"].append(latency)
                        self.metrics["total_sent"] += 1

                        async with get_db_session() as session:
                            await log_notification_sent(
                                session=session,
                                alert_id=item.alert_id,
                                user_id=item.user_id,
                                platform=item.platform,
                                notification_type=item.notification_type,
                                payload_hash=item.payload_hash,
                                show_key=item.show.show_id,
                                message_text=text,
                            )
                        logger.info(f"Sent notification to {item.chat_id} [{item.platform}] for {item.show.movie_title}")

                    except TelegramRetryAfter as retry_err:
                        logger.warning(f"Telegram 429 Retry-After {retry_err.retry_after}s for chat {item.chat_id}")
                        await asyncio.sleep(retry_err.retry_after)
                        await self._queue.put(item)
                    except TelegramAPIError as api_err:
                        err_msg = str(api_err).lower()
                        if "bot was blocked by the user" in err_msg or "user is deactivated" in err_msg:
                            logger.warning(f"User {item.chat_id} blocked bot. Marking user inactive in DB.")
                            async with get_db_session() as session:
                                await session.execute(
                                    update(User).where(User.telegram_id == item.chat_id).values(is_active=False)
                                )
                        elif "chat not found" in err_msg:
                            logger.warning(
                                f"⚠️ User {item.chat_id} has not started the bot yet. "
                                f"Telegram requires user to open @Tickets_NotifyBot and press /start."
                            )
                        else:
                            logger.error(f"Telegram API error sending to {item.chat_id}: {api_err}")
                        self.metrics["total_failed"] += 1
                    except Exception as send_err:
                        logger.error(f"Failed to send notification: {send_err}")
                        self.metrics["total_failed"] += 1

                self._queue.task_done()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Unexpected error in notification worker: {e}")
                await asyncio.sleep(1)


notifier = TelegramNotifier()
