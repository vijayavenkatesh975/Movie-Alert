"""Application configuration settings for TicketNotify."""

from typing import List, Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Telegram Bot
    BOT_TOKEN: str = Field(default="9094648730:AAGav3MwDbYgAABKejC0XUQwy9OupjJe2A0", description="Telegram Bot Token")
    ADMIN_ID: int = Field(default=1483331491, description="Telegram ID of the admin")
    TMDB_API_KEY: Optional[str] = Field(default=None, description="TMDB API key for upcoming movie discovery")

    # Database & Cache
    DATABASE_URL: str = Field(
        default="sqlite+aiosqlite:///./ticketnotify.db",
        description="SQLAlchemy async connection URL (PostgreSQL asyncpg or SQLite aiosqlite)"
    )
    REDIS_URL: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL (uses fakeredis automatically if server is unreachable)"
    )
    USE_IN_MEMORY_REDIS_FALLBACK: bool = Field(
        default=True,
        description="Fallback to in-memory async Redis if real Redis is unavailable"
    )

    # Webhook & Server
    WEBHOOK_MODE: bool = Field(default=False, description="Use webhook instead of long polling")
    WEBHOOK_URL: str = Field(default="", description="Public base URL for Telegram webhook (e.g. https://mybot.domain.com)")
    WEBHOOK_PATH: str = Field(default="/webhook", description="Path for Telegram webhook")
    WEBHOOK_SECRET: str = Field(default="ticketnotify_sec_key", description="Telegram webhook secret token")
    HOST: str = Field(default="0.0.0.0", description="FastAPI host")
    PORT: int = Field(default=8000, description="FastAPI port")

    # Proxies & Scraper
    PROXY_LIST: str = Field(default="", description="Comma-separated list of HTTP/SOCKS proxies")
    USER_AGENT_ROTATION: bool = Field(default=True, description="Rotate standard user agents")
    SCRAPER_REQUEST_TIMEOUT: float = Field(default=10.0, description="HTTP timeout for scrapers in seconds")

    # Polling & Rate Limits
    HOT_POLL_INTERVAL: int = Field(default=20, description="Polling interval in seconds for hot/imminent movies")
    IDLE_POLL_INTERVAL: int = Field(default=150, description="Polling interval in seconds for idle/future movies")
    GLOBAL_RATE_LIMIT_PER_SEC: int = Field(default=30, description="Telegram outbound global limit msgs/sec")
    CHAT_RATE_LIMIT_PER_SEC: float = Field(default=1.0, description="Telegram outbound per-chat limit msgs/sec")

    # Circuit Breakers
    CIRCUIT_BREAKER_MAX_FAILURES: int = Field(default=5, description="Failures before opening circuit breaker")
    CIRCUIT_BREAKER_RESET_TIMEOUT: int = Field(default=120, description="Seconds before half-open probe")

    # Observability
    TESTING: bool = Field(default=False, description="Set True during testing to skip background loops")
    LOG_LEVEL: str = Field(default="INFO", description="Log level: DEBUG, INFO, WARNING, ERROR")
    SENTRY_DSN: Optional[str] = Field(default=None, description="Optional Sentry DSN")
    PROMETHEUS_METRICS_ENABLED: bool = Field(default=True, description="Enable Prometheus metrics endpoint")

    @property
    def proxy_list_parsed(self) -> List[str]:
        if not self.PROXY_LIST or not self.PROXY_LIST.strip():
            return []
        return [p.strip() for p in self.PROXY_LIST.split(",") if p.strip()]


settings = Settings()
