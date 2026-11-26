"""Admin commands: /stats, /broadcast, /platform_status."""

import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy import select, func

from ticketnotify.config import settings
from ticketnotify.bot.states import AdminFlow
from ticketnotify.database.session import get_db_session
from ticketnotify.database.models import User, Alert, PlatformState, NotificationLog
from ticketnotify.adapters.registry import registry
from ticketnotify.engine.scheduler import scheduler

logger = logging.getLogger(__name__)
router = Router(name="admin_router")


def is_admin(user_id: int) -> bool:
    return user_id == settings.ADMIN_ID


@router.message(Command("stats"))
async def handle_admin_stats(message: Message):
    if not is_admin(message.from_user.id):
        return

    async with get_db_session() as session:
        user_count = await session.scalar(select(func.count(User.id)))
        alert_count = await session.scalar(select(func.count(Alert.id)).where(Alert.status == "active"))
        watch_count = await session.scalar(select(func.count(PlatformState.id)))
        notify_count = await session.scalar(select(func.count(NotificationLog.id)))

    m = scheduler.metrics
    avg_latency = (
        round(sum(m["poll_latencies_ms"]) / len(m["poll_latencies_ms"]), 1)
        if m["poll_latencies_ms"]
        else 0
    )

    stats_text = (
        "📊 *TicketNotify System Metrics*\n\n"
        f"👥 *Total Registered Users:* {user_count or 0}\n"
        f"🔔 *Active Alerts:* {alert_count or 0}\n"
        f"📡 *Unique Watch Targets:* {watch_count or 0}\n"
        f"📤 *Total Notifications Sent:* {notify_count or 0}\n\n"
        "⚡ *Engine Metrics:*\n"
        f"• Polling Cycles: {m['total_cycles']}\n"
        f"• Platform Polls Executed: {m['polls_executed']}\n"
        f"• Avg Poll Latency: {avg_latency} ms\n"
        f"• Last Poll Cycle: {m['last_poll_cycle'] or 'Pending'}"
    )
    await message.answer(stats_text, parse_mode="Markdown")


@router.message(Command("health"))
async def handle_health_command(message: Message):
    if not is_admin(message.from_user.id):
        return

    wait_msg = await message.answer("🔍 Gathering comprehensive system health metrics...")
    health = await registry.health_check_all()
    cb_statuses = registry.get_circuit_statuses()

    async with get_db_session() as session:
        active_alerts = await session.scalar(select(func.count(Alert.id)).where(Alert.status == "active"))
        total_users = await session.scalar(select(func.count(User.id)))

    from ticketnotify.adapters.proxy_manager import proxy_manager
    from ticketnotify.engine.notifier import notifier

    proxy_count = len(proxy_manager._proxies)
    active_proxies = sum(1 for p in proxy_manager._proxies.values() if p.is_active)

    lines = [
        "🏥 *TicketNotify System Health Report*\n",
        f"🖥 *System Status:* 🟢 Healthy",
        f"🤖 *Active Alerts Monitored:* {active_alerts or 0}",
        f"👥 *Total Users:* {total_users or 0}",
        f"🌐 *Proxy Pool:* {active_proxies}/{proxy_count} healthy",
        f"⚡ *Notifications Delivered:* {notifier.metrics['total_sent']} ({notifier.metrics['priority_sent']} priority)",
        f"❌ *Notifications Failed:* {notifier.metrics['total_failed']}\n",
        "*Platform Adapters:*",
    ]

    for cb in cb_statuses:
        p_name = cb["platform"].upper()
        state = cb["state"].upper()
        emoji = "🟢" if state == "CLOSED" else "🔴"
        live = "Live" if health.get(cb["platform"]) else "Fallback"
        lines.append(f"• *{p_name}*: {emoji} {state} ({live})")

    await wait_msg.edit_text("\n".join(lines), parse_mode="Markdown")


@router.message(Command("platform_status"))
async def handle_platform_status(message: Message):
    if not is_admin(message.from_user.id):
        return

    wait_msg = await message.answer("🔍 Checking all platform endpoints and circuit breakers...")
    health = await registry.health_check_all()
    cb_statuses = registry.get_circuit_statuses()

    status_lines = ["🛡 *Platform Health & Circuit Breaker Status:*\n"]
    for cb in cb_statuses:
        p_name = cb["platform"].upper()
        state = cb["state"].upper()
        state_emoji = "🟢" if state == "CLOSED" else ("🟡" if state == "HALF_OPEN" else "🔴")
        is_alive = "✅ Healthy" if health.get(cb["platform"]) else "⚠️ Degraded/Fallback"
        err = f" (Error: {cb['last_error']})" if cb.get("last_error") else ""

        status_lines.append(
            f"• *{p_name}*: {state_emoji} Circuit: `{state}` | API: {is_alive} | Failures: {cb['failure_count']}{err}"
        )

    await wait_msg.edit_text("\n".join(status_lines), parse_mode="Markdown")


@router.message(Command("broadcast"))
async def handle_broadcast_command(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    await message.answer(
        "📢 *Admin Broadcast Mode*\n\n"
        "Please type the announcement message you want to send to all active users:",
        parse_mode="Markdown",
    )
    await state.set_state(AdminFlow.waiting_for_broadcast)


@router.message(AdminFlow.waiting_for_broadcast)
async def process_broadcast_message(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return

    broadcast_text = message.text
    async with get_db_session() as session:
        users = (await session.scalars(select(User.telegram_id).where(User.is_active.is_(True)))).all()

    await state.clear()
    sent_count = 0
    bot = message.bot

    status_msg = await message.answer(f"🚀 Broadcasting to {len(users)} users...")

    for tid in users:
        try:
            await bot.send_message(
                chat_id=tid,
                text=f"📢 *TicketNotify Announcement:*\n\n{broadcast_text}",
                parse_mode="Markdown",
            )
            sent_count += 1
        except Exception as e:
            logger.warning(f"Could not deliver broadcast to {tid}: {e}")

    await status_msg.edit_text(f"✅ Broadcast finished. Sent to {sent_count}/{len(users)} users.")
