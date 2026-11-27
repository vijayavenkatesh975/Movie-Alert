"""FastAPI application with Telegram webhook, health checks, and Prometheus metrics."""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Dict, Any
import os
import subprocess
from fastapi import FastAPI, Request, Header, HTTPException, status
from fastapi.responses import JSONResponse, PlainTextResponse
from aiogram import Bot, Dispatcher
from aiogram.types import Update
from sqlalchemy import select, func

from ticketnotify.config import settings
from ticketnotify.database import init_db, get_db_session
from ticketnotify.database.models import User, Alert, PlatformState, NotificationLog
from ticketnotify.adapters.registry import registry
from ticketnotify.engine.scheduler import scheduler
from ticketnotify.bot import create_bot, create_dispatcher, init_bot_services
from ticketnotify.cache.redis import check_redis_health

logger = logging.getLogger(__name__)

bot: Bot = create_bot()
dp: Dispatcher = create_dispatcher()
polling_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global polling_task
    # If running in test mode, do not connect to external telegram APIs or DB or scheduler
    if settings.TESTING:
        yield
        return

    logger.info("Starting TicketNotify application...")

    # 1. Initialize database schema
    await init_db()

    # 2. Initialize bot & notifier services
    await init_bot_services(bot)

    # 3. Startup Self-Check
    db_type = "PostgreSQL" if "postgres" in settings.DATABASE_URL else "SQLite"
    try:
        async with get_db_session() as session:
            await session.scalar(select(1))
        logger.info(f"Startup DB check passed: connected to {db_type}")
    except Exception as e:
        logger.error(f"Startup DB connection failed: {e}")

    redis_ok, redis_desc = await check_redis_health()
    logger.info(f"Startup Redis check: {redis_desc}")

    if not settings.TMDB_API_KEY:
        logger.warning(
            "Startup Notice: TMDB_API_KEY is not set. Upcoming movie catalog from TMDB "
            "will be disabled; falling back to platform live catalogs only."
        )

    # Bot verification & Admin Startup notification
    try:
        me = await bot.get_me()
        logger.info(f"Connected to Telegram Bot: @{me.username} (ID: {me.id})")

        commit_hash = os.environ.get("RENDER_GIT_COMMIT") or os.environ.get("GIT_COMMIT")
        if not commit_hash:
            try:
                commit_hash = subprocess.check_output(
                    ["git", "rev-parse", "--short", "HEAD"], text=True
                ).strip()
            except Exception:
                commit_hash = "production"

        admin_startup_msg = (
            f"🚀 <b>TicketNotify Bot Started Successfully!</b>\n\n"
            f"🤖 <b>Bot:</b> @{me.username}\n"
            f"🏷 <b>Version:</b> 1.0.0\n"
            f"📌 <b>Commit:</b> <code>{commit_hash}</code>\n"
            f"🗄 <b>Database:</b> Connected ({db_type})\n"
            f"⚡ <b>Redis:</b> {redis_desc}\n"
            f"🎬 <b>TMDB:</b> {'Configured ✅' if settings.TMDB_API_KEY else 'Missing ⚠️ (upcoming discovery limited)'}\n"
            f"🌐 <b>Mode:</b> {'Webhook' if settings.WEBHOOK_MODE else 'Long Polling'}\n"
            f"⏱ <b>Direct IP Cap:</b> {'Active (>=5.0s)' if not settings.proxy_list_parsed else 'Proxied'}"
        )
        try:
            await bot.send_message(chat_id=settings.ADMIN_ID, text=admin_startup_msg, parse_mode="HTML")
        except Exception as se:
            logger.debug(f"Could not deliver startup message to admin {settings.ADMIN_ID}: {se}")
    except Exception as be:
        logger.warning(f"Could not verify Telegram bot via getMe: {be}")

    # 4. Start adaptive polling scheduler
    await scheduler.start()

    # 5. Webhook vs Polling mode
    if settings.WEBHOOK_MODE and settings.WEBHOOK_URL:
        full_webhook_url = f"{settings.WEBHOOK_URL.rstrip('/')}{settings.WEBHOOK_PATH}"
        logger.info(f"Setting Telegram webhook to: {full_webhook_url}")
        await bot.set_webhook(
            url=full_webhook_url,
            secret_token=settings.WEBHOOK_SECRET,
            drop_pending_updates=True,
        )
    else:
        logger.info("Starting aiogram long-polling background worker (local/dev mode)...")
        # Ensure any old webhook is deleted
        try:
            await bot.delete_webhook(drop_pending_updates=True)
        except Exception as e:
            logger.warning(f"Could not delete old webhook: {e}")
        polling_task = asyncio.create_task(dp.start_polling(bot, handle_signals=False))

    yield

    logger.info("Shutting down TicketNotify application...")
    if polling_task:
        polling_task.cancel()
        try:
            await polling_task
        except asyncio.CancelledError:
            pass

    await scheduler.stop()
    await bot.session.close()
    logger.info("Shutdown complete.")


app = FastAPI(
    title="TicketNotify API",
    description="Real-time multi-platform cinema booking alert service",
    version="1.0.0",
    lifespan=lifespan,
)


@app.post(settings.WEBHOOK_PATH)
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(None),
):
    """Processes incoming Telegram updates via Webhook."""
    if settings.WEBHOOK_SECRET and x_telegram_bot_api_secret_token != settings.WEBHOOK_SECRET:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook secret")

    try:
        body = await request.json()
        update = Update.model_validate(body, context={"bot": bot})
        await dp.feed_update(bot, update)
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Error processing webhook update: {e}")
        return {"status": "error", "message": str(e)}


@app.get("/")
async def root():
    """Root health and status endpoint."""
    return {
        "service": "TicketNotify",
        "status": "running",
        "bot": "@Tickets_NotifyBot",
        "scheduler_running": scheduler._running,
    }


@app.get("/health")
async def health_check():
    """Cheap system health check (no DB/Redis hits) for UptimeRobot and load balancers."""
    return {
        "status": "healthy",
        "service": "TicketNotify",
        "scheduler_running": scheduler._running,
    }


@app.get("/ready")
async def readiness_check():
    """Readiness probe verifying database and Redis connectivity."""
    db_ok = False
    db_error = None
    try:
        async with get_db_session() as session:
            await session.scalar(select(1))
        db_ok = True
    except Exception as e:
        db_error = str(e)
        logger.error(f"Readiness check DB error: {e}")

    redis_ok, redis_desc = await check_redis_health()
    is_ready = db_ok and redis_ok

    status_code = status.HTTP_200_OK if is_ready else status.HTTP_503_SERVICE_UNAVAILABLE

    return JSONResponse(
        status_code=status_code,
        content={
            "status": "ready" if is_ready else "not_ready",
            "database": "connected" if db_ok else f"error: {db_error}",
            "redis": redis_desc,
            "scheduler_running": scheduler._running,
        },
    )


@app.get("/api/platforms/status")
async def platform_status():
    """Platform adapter health check and circuit breaker inspection."""
    platform_health = await registry.health_check_all()
    circuit_statuses = registry.get_circuit_statuses()
    return {
        "platforms": platform_health,
        "circuit_breakers": circuit_statuses,
    }


@app.get("/metrics")
async def prometheus_metrics():
    """Prometheus-formatted metrics."""
    async with get_db_session() as session:
        user_count = await session.scalar(select(func.count(User.id))) or 0
        alert_count = await session.scalar(select(func.count(Alert.id)).where(Alert.status == "active")) or 0
        watch_count = await session.scalar(select(func.count(PlatformState.id))) or 0
        notify_count = await session.scalar(select(func.count(NotificationLog.id))) or 0

    m = scheduler.metrics
    avg_lat = (
        round(sum(m["poll_latencies_ms"]) / len(m["poll_latencies_ms"]), 2)
        if m["poll_latencies_ms"]
        else 0.0
    )

    lines = [
        "# HELP ticketnotify_active_users Total registered users",
        "# TYPE ticketnotify_active_users gauge",
        f"ticketnotify_active_users {user_count}",
        "",
        "# HELP ticketnotify_active_alerts Active movie alerts",
        "# TYPE ticketnotify_active_alerts gauge",
        f"ticketnotify_active_alerts {alert_count}",
        "",
        "# HELP ticketnotify_unique_watches Unique (movie, city, platform) watch targets",
        "# TYPE ticketnotify_unique_watches gauge",
        f"ticketnotify_unique_watches {watch_count}",
        "",
        "# HELP ticketnotify_notifications_sent Total notifications sent",
        "# TYPE ticketnotify_notifications_sent counter",
        f"ticketnotify_notifications_sent {notify_count}",
        "",
        "# HELP ticketnotify_poll_latency_ms Average polling latency in ms",
        "# TYPE ticketnotify_poll_latency_ms gauge",
        f"ticketnotify_poll_latency_ms {avg_lat}",
        "",
        "# HELP ticketnotify_total_polls Total platform queries executed",
        "# TYPE ticketnotify_total_polls counter",
        f"ticketnotify_total_polls {m['polls_executed']}",
    ]

    # Circuit breaker states (1=CLOSED/healthy, 0=OPEN/tripped)
    for cb in registry.get_circuit_statuses():
        state_val = 1 if cb["state"] == "closed" else 0
        lines.append(f'ticketnotify_circuit_state{{platform="{cb["platform"]}"}} {state_val}')

    return PlainTextResponse("\n".join(lines) + "\n")


@app.get("/api/admin/status")
async def admin_status_api():
    """JSON admin status."""
    async with get_db_session() as session:
        user_count = await session.scalar(select(func.count(User.id))) or 0
        alert_count = await session.scalar(select(func.count(Alert.id)).where(Alert.status == "active")) or 0
        watch_count = await session.scalar(select(func.count(PlatformState.id))) or 0
        notify_count = await session.scalar(select(func.count(NotificationLog.id))) or 0

    return {
        "users": user_count,
        "active_alerts": alert_count,
        "unique_watches": watch_count,
        "notifications_sent": notify_count,
        "scheduler_metrics": scheduler.metrics,
        "circuit_breakers": registry.get_circuit_statuses(),
    }
