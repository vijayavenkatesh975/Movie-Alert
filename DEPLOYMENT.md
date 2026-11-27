# 🚀 TicketNotify Deployment Guide (Render & Production)

This guide walks you through deploying **TicketNotify** (@Tickets_NotifyBot) for 24/7 continuous operation on [Render](https://render.com).

---

## 1. Region Recommendation: Singapore (`singapore`)

> [!IMPORTANT]
> When creating your service on Render, choose **Singapore (Southeast Asia)**.
> 
> **Why?**
> Indian cinema booking platforms (BookMyShow, PVR INOX, District) host their servers and CDNs in Mumbai, Chennai, and Singapore.
> - **Singapore ➡️ India**: ~30ms - 45ms latency.
> - **US Ohio (Default) ➡️ India**: ~250ms - 320ms latency and higher risk of Akamai geo-blocking.

---

## 2. Choosing Deployment Architecture on Render

TicketNotify supports two modes on Render:

### Option A: Web Service with Long Polling + Cheap Health Check (Recommended for Free Tier)
- **Type**: Web Service (Docker or Python 3.11)
- **Runtime**: Python or Docker
- **Instance Type**: Free ($0/mo) or Starter ($7/mo)
- **How it works**:
  - The bot runs an internal long-polling background worker (`dp.start_polling`).
  - FastAPI exposes `/health` on port `10000` (or `$PORT`).
  - **UptimeRobot** pings `/health` every 10 minutes to prevent the free instance from sleeping.
  - `/health` does zero database hits, ensuring ultra-cheap CPU usage.

### Option B: Web Service with Webhook Mode (Recommended for Zero-Latency Scaling)
- **Type**: Web Service
- **Environment**:
  - `WEBHOOK_MODE=true`
  - `WEBHOOK_URL=https://<your-service-name>.onrender.com`
  - `WEBHOOK_SECRET=<random-32-char-token>`
- Telegram posts updates directly to `https://<your-service-name>.onrender.com/webhook` with signature verification.

---

## 3. Database & Redis Setup on Render

### PostgreSQL
1. On the Render Dashboard, click **New +** ➡️ **PostgreSQL**.
2. Set Region to **Singapore**.
3. Once created, copy the **Internal Database URL** (e.g. `postgres://user:password@dpg-xxx:5432/ticketnotify`).
4. In your Web Service Environment Variables, set `DATABASE_URL` to this value.
   - *Note: TicketNotify automatically converts `postgres://` to `postgresql+asyncpg://` at runtime.*

### Redis Cache
1. Click **New +** ➡️ **Redis**.
2. Set Region to **Singapore**.
3. Copy the **Internal Redis URL** (e.g. `redis://red-xxx:6379`).
4. In your Web Service Environment Variables, set `REDIS_URL` to this value.
5. If running without Render Redis, set `USE_IN_MEMORY_REDIS_FALLBACK=true` (TicketNotify will automatically use in-memory `fakeredis`).

---

## 4. Environment Variables Checklist

Set these in **Environment Variables** in your Render service settings:

| Variable | Recommended Value | Description |
| :--- | :--- | :--- |
| `BOT_TOKEN` | `9094648730:AAG...` | Bot token from @BotFather |
| `ADMIN_ID` | `1483331491` | Admin Telegram User ID for startup alerts |
| `TMDB_API_KEY` | *(your TMDB API key)* | Optional for upcoming movie catalog and countdowns |
| `DATABASE_URL` | `postgresql+asyncpg://...` or sqlite | Database connection string |
| `REDIS_URL` | `redis://...` | Redis cache connection string |
| `USE_IN_MEMORY_REDIS_FALLBACK` | `true` | Fall back to in-memory cache if Redis is down |
| `WEBHOOK_MODE` | `false` | `false` for long-polling worker, `true` for webhook |
| `PORT` | `10000` | Port automatically assigned by Render |
| `TZ` | `Asia/Kolkata` | Set instance timezone to Indian Standard Time |
| `LOG_LEVEL` | `INFO` | Logging verbosity |
| `HOT_POLL_INTERVAL` | `20` | Polling frequency for active releases |
| `PROXY_LIST` | *(optional)* | Comma-separated residential proxies to prevent datacenter rate limits |

---

## 5. Connecting UptimeRobot (24/7 Keep-Alive)

On Render's Free tier, services spin down after 15 minutes of inactivity. To keep TicketNotify running 24/7:

1. Create a free account at [UptimeRobot.com](https://uptimerobot.com).
2. Click **Add New Monitor**.
3. Configure the monitor:
   - **Monitor Type**: `HTTP(s)`
   - **Friendly Name**: `TicketNotify Bot Health`
   - **URL (or IP)**: `https://<your-service-name>.onrender.com/health`
   - **Monitoring Interval**: `10 minutes` (Render sleeps after 15 min; 10 min keeps it awake)
4. Click **Create Monitor**.

> [!TIP]
> The `/health` endpoint is lightweight and performs no database or scraper calls. It will never inflate database connection pools or trigger scraper rate limits.
> To inspect database and cache connectivity, use the `/ready` endpoint instead.

---

## 6. Verification Endpoints

- **Root info**: `GET /`
- **Cheap keep-alive**: `GET /health` (Returns `{"status": "healthy"}`)
- **Readiness check**: `GET /ready` (Verifies DB & Redis: returns HTTP 200 or 503)
- **Adapter status**: `GET /api/platforms/status` (Health checks and circuit breaker state)
- **Metrics**: `GET /metrics` (Prometheus-formatted scraper & queue metrics)
