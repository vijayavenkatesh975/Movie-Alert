"""CRUD operations for users, locations, alerts, platform state, and notifications."""

from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy import select, update, delete, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ticketnotify.database.models import (
    User,
    Location,
    Alert,
    PlatformState,
    NotificationLog,
)


# --- User CRUD ---

async def get_or_create_user(
    session: AsyncSession,
    telegram_id: int,
    username: Optional[str] = None,
    first_name: Optional[str] = None,
) -> tuple[User, bool]:
    stmt = select(User).where(User.telegram_id == telegram_id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    
    if user:
        # Update username/first_name if changed
        if username and user.username != username:
            user.username = username
        if first_name and user.first_name != first_name:
            user.first_name = first_name
        return user, False

    user = User(
        telegram_id=telegram_id,
        username=username,
        first_name=first_name,
        language="en",
    )
    session.add(user)
    await session.flush()
    return user, True


async def get_user_by_telegram_id(session: AsyncSession, telegram_id: int) -> Optional[User]:
    stmt = select(User).where(User.telegram_id == telegram_id).options(selectinload(User.locations))
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def update_user_language(session: AsyncSession, user_id: int, language: str) -> None:
    stmt = update(User).where(User.id == user_id).values(language=language, updated_at=datetime.utcnow())
    await session.execute(stmt)


async def update_user_quiet_hours(
    session: AsyncSession,
    user_id: int,
    enabled: bool,
    start_hour: int = 23,
    end_hour: int = 7,
) -> None:
    stmt = update(User).where(User.id == user_id).values(
        quiet_hours_enabled=enabled,
        quiet_hours_start=start_hour,
        quiet_hours_end=end_hour,
        updated_at=datetime.utcnow(),
    )
    await session.execute(stmt)


async def update_user_selected_theatres(
    session: AsyncSession,
    user_id: int,
    theatre_data: Dict[str, Any],
    chains: Optional[List[str]] = None,
) -> None:
    """Persists user default city-wide theatre selection and preferred chains."""
    values: Dict[str, Any] = {
        "selected_theatres": theatre_data,
        "updated_at": datetime.utcnow(),
    }
    if chains is not None:
        values["selected_chains"] = chains
    stmt = update(User).where(User.id == user_id).values(**values)
    await session.execute(stmt)


async def update_user_notification_preferences(
    session: AsyncSession,
    user_id: int,
    prefs: Dict[str, bool],
) -> None:
    """Updates user notification trigger preferences (bookings_opened, price_drop, etc.)."""
    stmt = update(User).where(User.id == user_id).values(
        notification_preferences=prefs,
        updated_at=datetime.utcnow(),
    )
    await session.execute(stmt)


async def set_user_alerts_paused(
    session: AsyncSession,
    user_id: int,
    paused: bool,
) -> None:
    """Pauses or resumes all alert notifications for user."""
    stmt = update(User).where(User.id == user_id).values(
        alerts_paused=paused,
        updated_at=datetime.utcnow(),
    )
    await session.execute(stmt)


async def set_user_snooze(
    session: AsyncSession,
    user_id: int,
    snooze_until: Optional[datetime],
) -> None:
    """Snoozes all notifications until specified timestamp."""
    stmt = update(User).where(User.id == user_id).values(
        snoozed_until=snooze_until,
        updated_at=datetime.utcnow(),
    )
    await session.execute(stmt)


async def delete_user_data_gdpr(session: AsyncSession, telegram_id: int) -> bool:
    """GDPR-friendly wipe: permanently delete all data associated with telegram_id."""
    stmt = select(User).where(User.telegram_id == telegram_id)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        return False
    
    await session.delete(user)
    await session.flush()
    return True


# --- Location CRUD ---

async def create_location(
    session: AsyncSession,
    user_id: int,
    name: str,
    normalized_city: str,
    normalized_country: str,
    country_code: str,
    latitude: float,
    longitude: float,
    radius_km: float = 20.0,
    platform_mappings: Optional[Dict[str, Any]] = None,
    is_default: bool = False,
) -> Location:
    if is_default:
        # Reset any existing default
        await session.execute(
            update(Location).where(Location.user_id == user_id).values(is_default=False)
        )

    loc = Location(
        user_id=user_id,
        name=name,
        normalized_city=normalized_city,
        normalized_country=normalized_country,
        country_code=country_code,
        latitude=latitude,
        longitude=longitude,
        radius_km=radius_km,
        platform_mappings=platform_mappings or {},
        is_default=is_default,
    )
    session.add(loc)
    await session.flush()

    if is_default:
        await session.execute(
            update(User).where(User.id == user_id).values(default_location_id=loc.id)
        )

    return loc


async def get_user_locations(session: AsyncSession, user_id: int) -> List[Location]:
    stmt = select(Location).where(Location.user_id == user_id).order_by(Location.is_default.desc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_default_location(session: AsyncSession, user_id: int) -> Optional[Location]:
    stmt = select(Location).where(
        Location.user_id == user_id,
        Location.is_default.is_(True)
    )
    result = await session.execute(stmt)
    loc = result.scalar_one_or_none()
    if not loc:
        # Fallback to the first location if none is explicitly marked default
        stmt_first = select(Location).where(Location.user_id == user_id).limit(1)
        res = await session.execute(stmt_first)
        loc = res.scalar_one_or_none()
    return loc


# --- Alert CRUD ---

async def create_alert(
    session: AsyncSession,
    user_id: int,
    movie_query: str,
    location_id: int,
    platforms: List[str],
    movie_ids_by_platform: Optional[Dict[str, str]] = None,
    selected_cinemas: Optional[Dict[str, Any]] = None,
    filters_json: Optional[Dict[str, Any]] = None,
    alert_types: Optional[List[str]] = None,
    seats_needed: int = 1,
    must_be_consecutive: bool = True,
    row_zone: str = "any",
    column_zone: str = "any",
    seat_category: str = "any",
    max_price_per_seat: Optional[float] = None,
    urgency: str = "WARM",
) -> Alert:
    default_alert_types = [
        "bookings_opened",
        "new_show_added",
        "seats_filling_fast",
        "price_drop",
        "specific_cinema_opened",
    ]
    alert = Alert(
        user_id=user_id,
        movie_query=movie_query,
        movie_ids_by_platform=movie_ids_by_platform or {},
        location_id=location_id,
        platforms=platforms,
        selected_cinemas=selected_cinemas or {},
        filters_json=filters_json or {},
        alert_types=alert_types or default_alert_types,
        seats_needed=seats_needed,
        must_be_consecutive=must_be_consecutive,
        row_zone=row_zone,
        column_zone=column_zone,
        seat_category=seat_category,
        max_price_per_seat=max_price_per_seat,
        urgency=urgency,
        status="active",
        is_muted=False,
    )
    session.add(alert)
    await session.flush()
    return alert


async def update_alert_cinemas(
    session: AsyncSession,
    alert_id: int,
    selected_cinemas: Dict[str, Any],
) -> None:
    stmt = (
        update(Alert)
        .where(Alert.id == alert_id)
        .values(selected_cinemas=selected_cinemas, updated_at=datetime.utcnow())
    )
    await session.execute(stmt)


async def update_alert_seat_prefs(
    session: AsyncSession,
    alert_id: int,
    seats_needed: int = 1,
    must_be_consecutive: bool = True,
    row_zone: str = "any",
    column_zone: str = "any",
    seat_category: str = "any",
    max_price_per_seat: Optional[float] = None,
) -> None:
    stmt = (
        update(Alert)
        .where(Alert.id == alert_id)
        .values(
            seats_needed=seats_needed,
            must_be_consecutive=must_be_consecutive,
            row_zone=row_zone,
            column_zone=column_zone,
            seat_category=seat_category,
            max_price_per_seat=max_price_per_seat,
            updated_at=datetime.utcnow(),
        )
    )
    await session.execute(stmt)


async def update_alert_urgency(session: AsyncSession, alert_id: int, urgency: str) -> None:
    stmt = update(Alert).where(Alert.id == alert_id).values(urgency=urgency, updated_at=datetime.utcnow())
    await session.execute(stmt)


async def get_alert_by_id(session: AsyncSession, alert_id: int) -> Optional[Alert]:
    stmt = select(Alert).where(Alert.id == alert_id).options(
        selectinload(Alert.location),
        selectinload(Alert.user)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_user_alerts(session: AsyncSession, user_id: int) -> List[Alert]:
    stmt = select(Alert).where(
        Alert.user_id == user_id,
        Alert.status != "deleted"
    ).options(selectinload(Alert.location)).order_by(Alert.created_at.desc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def update_alert_status(session: AsyncSession, alert_id: int, status: str) -> None:
    stmt = update(Alert).where(Alert.id == alert_id).values(status=status, updated_at=datetime.utcnow())
    await session.execute(stmt)


async def set_alert_mute(session: AsyncSession, alert_id: int, is_muted: bool) -> None:
    stmt = update(Alert).where(Alert.id == alert_id).values(is_muted=is_muted, updated_at=datetime.utcnow())
    await session.execute(stmt)


async def delete_alert(session: AsyncSession, alert_id: int) -> None:
    stmt = update(Alert).where(Alert.id == alert_id).values(status="deleted", updated_at=datetime.utcnow())
    await session.execute(stmt)


async def get_all_active_alerts(session: AsyncSession) -> List[Alert]:
    stmt = select(Alert).where(
        Alert.status == "active",
        Alert.is_muted.is_(False)
    ).options(
        selectinload(Alert.location),
        selectinload(Alert.user)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


# --- Platform State CRUD ---

async def get_or_create_platform_state(
    session: AsyncSession,
    alert_key: str,
    platform: str,
    movie_identifier: str,
    city_identifier: str,
) -> PlatformState:
    stmt = select(PlatformState).where(
        PlatformState.alert_key == alert_key,
        PlatformState.platform == platform
    )
    result = await session.execute(stmt)
    state = result.scalar_one_or_none()
    
    if not state:
        state = PlatformState(
            alert_key=alert_key,
            platform=platform,
            movie_identifier=movie_identifier,
            city_identifier=city_identifier,
            last_snapshot_hash="",
            last_snapshot_data={},
            check_count=0,
            consecutive_failures=0,
            is_hot=False,
        )
        session.add(state)
        await session.flush()
    return state


async def update_platform_state_snapshot(
    session: AsyncSession,
    state_id: int,
    snapshot_hash: str,
    snapshot_data: Dict[str, Any],
    is_hot: bool = False,
) -> None:
    stmt = update(PlatformState).where(PlatformState.id == state_id).values(
        last_snapshot_hash=snapshot_hash,
        last_snapshot_data=snapshot_data,
        last_checked_at=datetime.utcnow(),
        check_count=PlatformState.check_count + 1,
        consecutive_failures=0,
        is_hot=is_hot,
        updated_at=datetime.utcnow(),
    )
    await session.execute(stmt)


async def record_platform_state_failure(session: AsyncSession, state_id: int) -> int:
    stmt = update(PlatformState).where(PlatformState.id == state_id).values(
        consecutive_failures=PlatformState.consecutive_failures + 1,
        last_checked_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    ).returning(PlatformState.consecutive_failures)
    result = await session.execute(stmt)
    val = result.scalar_one_or_none()
    return val or 1


# --- Notification Log CRUD ---

async def is_notification_duplicate(
    session: AsyncSession,
    alert_id: int,
    platform: str,
    payload_hash: str,
) -> bool:
    stmt = select(NotificationLog.id).where(
        NotificationLog.alert_id == alert_id,
        NotificationLog.platform == platform,
        NotificationLog.payload_hash == payload_hash
    ).limit(1)
    result = await session.execute(stmt)
    return result.scalar_one_or_none() is not None


async def log_notification_sent(
    session: AsyncSession,
    alert_id: int,
    user_id: int,
    platform: str,
    notification_type: str,
    payload_hash: str,
    show_key: Optional[str] = None,
    message_text: Optional[str] = None,
) -> NotificationLog:
    log = NotificationLog(
        alert_id=alert_id,
        user_id=user_id,
        platform=platform,
        notification_type=notification_type,
        payload_hash=payload_hash,
        show_key=show_key,
        message_text=message_text,
        sent_at=datetime.utcnow(),
    )
    session.add(log)
    await session.flush()
    return log
