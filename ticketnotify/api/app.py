"""FastAPI application with Telegram webhook, health checks, and Prometheus metrics."""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Dict, Any
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

    # 3. Start adaptive polling scheduler
    await scheduler.start()

    # 4. Webhook vs Polling mode
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
    """System health check verifying database and platforms."""
    # Check DB
    db_ok = False
    try:
        async with get_db_session() as session:
            await session.scalar(select(1))
        db_ok = True
    except Exception as e:
        logger.error(f"Health check DB failure: {e}")

    # Check platforms
    platform_health = await registry.health_check_all()
    circuit_statuses = registry.get_circuit_statuses()

    status_code = status.HTTP_200_OK if db_ok else status.HTTP_503_SERVICE_UNAVAILABLE

    return JSONResponse(
        status_code=status_code,
        content={
            "status": "healthy" if db_ok else "unhealthy",
            "database": "connected" if db_ok else "disconnected",
            "scheduler_running": scheduler._running,
            "platforms": platform_health,
            "circuit_breakers": circuit_statuses,
        },
    )


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
