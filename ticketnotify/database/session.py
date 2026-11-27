"""Database session management and engine initialization."""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy import event

from ticketnotify.config import settings
from ticketnotify.database.models import Base

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        db_url = settings.DATABASE_URL
        # Auto-normalize PostgreSQL scheme for SQLAlchemy asyncpg
        if db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif db_url.startswith("postgresql://") and "+asyncpg" not in db_url:
            db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

        # Configure engine options
        connect_args = {}
        if db_url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        
        _engine = create_async_engine(
            db_url,
            echo=False,
            future=True,
            connect_args=connect_args,
        )

        # Enable SQLite Foreign Keys support
        if db_url.startswith("sqlite"):
            @event.listens_for(_engine.sync_engine, "connect")
            def set_sqlite_pragma(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        engine = get_engine()
        _session_factory = async_sessionmaker(
            bind=engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


async def init_db() -> None:
    """Create tables if they do not exist, and safely migrate new columns."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
        # Safe column additions for SQLite if upgrading existing database
        if settings.DATABASE_URL.startswith("sqlite"):
            from sqlalchemy import text
            def _migrate_sqlite_columns(sync_conn):
                cursor = sync_conn.connection.cursor()
                cursor.execute("PRAGMA table_info(alerts)")
                existing_cols = {row[1] for row in cursor.fetchall()}
                new_columns = [
                    ("selected_cinemas", "JSON DEFAULT '{}'"),
                    ("seat_mode", "VARCHAR(20) DEFAULT 'zone'"),
                    ("exact_seats", "JSON DEFAULT '[]'"),
                    ("seats_needed", "INTEGER DEFAULT 1"),
                    ("must_be_consecutive", "BOOLEAN DEFAULT 1"),
                    ("row_zone", "VARCHAR(20) DEFAULT 'any'"),
                    ("column_zone", "VARCHAR(20) DEFAULT 'any'"),
                    ("seat_category", "VARCHAR(50) DEFAULT 'any'"),
                    ("max_price_per_seat", "FLOAT DEFAULT NULL"),
                    ("urgency", "VARCHAR(20) DEFAULT 'WARM'"),
                    ("languages_filter", "JSON DEFAULT '[]'"),
                    ("formats_filter", "JSON DEFAULT '[]'"),
                    ("time_window_start", "VARCHAR(10) DEFAULT NULL"),
                    ("time_window_end", "VARCHAR(10) DEFAULT NULL"),
                ]
                for col_name, col_def in new_columns:
                    if col_name not in existing_cols:
                        cursor.execute(f"ALTER TABLE alerts ADD COLUMN {col_name} {col_def}")

                # Migrate user table columns
                cursor.execute("PRAGMA table_info(users)")
                existing_user_cols = {row[1] for row in cursor.fetchall()}
                new_user_columns = [
                    ("selected_theatres", "JSON DEFAULT '{}'"),
                    ("selected_chains", "JSON DEFAULT '[]'"),
                    ("notification_preferences", "JSON DEFAULT '{}'"),
                    ("alerts_paused", "BOOLEAN DEFAULT 0"),
                    ("snoozed_until", "DATETIME DEFAULT NULL"),
                    ("non_critical_frequency", "VARCHAR(20) DEFAULT 'instant'"),
                ]
                for col_name, col_def in new_user_columns:
                    if col_name not in existing_user_cols:
                        cursor.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_def}")

                cursor.close()
            await conn.run_sync(_migrate_sqlite_columns)
            
    logger.info("Database schema initialized successfully.")


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide a transactional scope around a series of operations."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
