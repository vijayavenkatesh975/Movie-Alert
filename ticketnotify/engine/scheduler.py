"""Adaptive polling scheduler grouping watches and diffing state changes."""

import asyncio
import logging
import time
from datetime import datetime
from typing import Dict, List, Set, Any, Optional

from ticketnotify.config import settings
from ticketnotify.database.session import get_db_session
from ticketnotify.database.crud import (
    get_all_active_alerts,
    get_or_create_platform_state,
    update_platform_state_snapshot,
    record_platform_state_failure,
)
from ticketnotify.database.models import Alert
from ticketnotify.adapters.registry import registry
from ticketnotify.adapters.base import Show
from ticketnotify.engine.diff_engine import (
    DiffEngine,
    compute_snapshot_hash,
    compute_event_payload_hash,
)
from ticketnotify.engine.notifier import notifier

logger = logging.getLogger(__name__)


class WatchGroup:
    """Represents a grouped watch target: (platform, movie_id, city_identifier)."""

    def __init__(self, platform: str, movie_id: str, city_identifier: str, movie_title: str):
        self.platform = platform
        self.movie_id = movie_id
        self.city_identifier = city_identifier
        self.movie_title = movie_title
        self.alerts: List[Alert] = []
        self.is_hot: bool = False
        self.last_polled_at: float = 0.0

    @property
    def key(self) -> str:
        return f"{self.platform}:{self.city_identifier.lower()}:{self.movie_id}"


class AdaptiveScheduler:
    def __init__(self):
        self._running = False
        self._scheduler_task: Optional[asyncio.Task] = None
        self._watch_groups: Dict[str, WatchGroup] = {}
        self._last_polled_times: Dict[str, float] = {}
        self.metrics: Dict[str, Any] = {
            "last_poll_cycle": None,
            "total_cycles": 0,
            "polls_executed": 0,
            "notifications_generated": 0,
            "poll_latencies_ms": [],
        }

    async def start(self) -> None:
        """Starts background adaptive scheduler."""
        if self._running:
            return
        self._running = True
        self._scheduler_task = asyncio.create_task(self._run_loop())
        logger.info("Adaptive polling scheduler started.")

    async def stop(self) -> None:
        """Stops background scheduler."""
        self._running = False
        if self._scheduler_task:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass
        logger.info("Adaptive polling scheduler stopped.")

    async def poll_once(self) -> None:
        """Executes a single cycle of adaptive grouping and polling (useful for manual runs & tests)."""
        await self._cycle()

    async def _run_loop(self) -> None:
        while self._running:
            try:
                start_cycle = time.time()
                await self._cycle()
                self.metrics["last_poll_cycle"] = datetime.utcnow().isoformat()
                self.metrics["total_cycles"] += 1

                # Sleep 1s per tick to service HOT watches (1-3s) without lag
                elapsed = time.time() - start_cycle
                sleep_time = max(0.5, 1.0 - elapsed)
                await asyncio.sleep(sleep_time)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in scheduler loop: {e}", exc_info=True)
                await asyncio.sleep(5)

    async def _cycle(self) -> None:
        """Single grouping and evaluation cycle."""
        # Step 1: Fetch all active alerts from database
        async with get_db_session() as session:
            alerts = await get_all_active_alerts(session)

        if not alerts:
            return

        # Step 2: Group identical (platform, movie_id, city) watches into ONE WatchGroup
        current_groups: Dict[str, WatchGroup] = {}
        for alert in alerts:
            if not alert.location:
                continue

            city_norm = alert.location.normalized_city or "default"
            platforms = alert.platforms or []

            for platform in platforms:
                movie_id = alert.movie_ids_by_platform.get(platform)
                if not movie_id:
                    # Use fallback ID generated from query if not explicitly set
                    movie_id = f"Q_{hash(alert.movie_query.lower()) % 10000000:07d}"

                group_key = f"{platform}:{city_norm.lower()}:{movie_id}"
                if group_key not in current_groups:
                    current_groups[group_key] = WatchGroup(
                        platform=platform,
                        movie_id=movie_id,
                        city_identifier=city_norm,
                        movie_title=alert.movie_query,
                    )
                current_groups[group_key].alerts.append(alert)

                # Check if group is "hot" (e.g. tracking bookings_opened or high alert volume)
                if "bookings_opened" in alert.alert_types or len(current_groups[group_key].alerts) >= 3:
                    current_groups[group_key].is_hot = True

        self._watch_groups = current_groups

        # Step 3: For each WatchGroup, check if its polling interval has elapsed
        now = time.time()
        for group in self._watch_groups.values():
            # Adaptive tiering: HOT (1-3s), WARM (10-15s), COLD (60-120s)
            urgencies = [getattr(a, "urgency", "WARM") for a in group.alerts]
            if "HOT" in urgencies or group.is_hot:
                interval = 2.0
            elif "WARM" in urgencies:
                interval = 12.0
            else:
                interval = 60.0

            last_polled = self._last_polled_times.get(group.key, 0.0)
            if now - last_polled >= interval:
                await self._poll_group(group)
                self._last_polled_times[group.key] = time.time()

    async def _poll_group(self, group: WatchGroup) -> None:
        """Polls one platform watch for all users tracking it."""
        platform = group.platform
        movie_id = group.movie_id
        alert_key = group.key
        sample_location = group.alerts[0].location

        # Check circuit breaker
        if not registry.is_platform_available(platform):
            logger.debug(f"Circuit breaker for [{platform}] is OPEN. Skipping watch group {alert_key}")
            return

        t0 = time.time()
        try:
            # Single HTTP request to platform adapter returning typed FetchResult
            fetch_res = await registry.get_shows(platform, movie_id, sample_location)
            poll_latency = (time.time() - t0) * 1000.0
            self.metrics["poll_latencies_ms"].append(poll_latency)
            if len(self.metrics["poll_latencies_ms"]) > 100:
                self.metrics["poll_latencies_ms"].pop(0)

            # If platform failed, was blocked, or had parse error: NEVER update state or notify!
            if not fetch_res.is_success:
                logger.warning(
                    f"Poll for {alert_key} on {platform.upper()} failed [{fetch_res.status.value}]: "
                    f"{fetch_res.error_message}. Preserving last-known state."
                )
                async with get_db_session() as session:
                    state = await get_or_create_platform_state(
                        session=session,
                        alert_key=alert_key,
                        platform=platform,
                        movie_identifier=movie_id,
                        city_identifier=group.city_identifier,
                    )
                    await record_platform_state_failure(session, state.id)
                return

            new_shows = fetch_res.shows
            self.metrics["polls_executed"] += 1

            # Fetch existing state snapshot from database
            async with get_db_session() as session:
                state = await get_or_create_platform_state(
                    session=session,
                    alert_key=alert_key,
                    platform=platform,
                    movie_identifier=movie_id,
                    city_identifier=group.city_identifier,
                )

                old_snapshot = state.last_snapshot_data or {}
                new_hash = compute_snapshot_hash(new_shows)
                is_initial_baseline = (not state.last_snapshot_hash)

                # Check if shows changed
                if new_hash != state.last_snapshot_hash:
                    # Run diff engine with initial baseline protection
                    diff_events = DiffEngine.diff(
                        old_snapshot=old_snapshot,
                        new_shows=new_shows,
                        platform=platform,
                        movie_id=movie_id,
                        is_initial_baseline=is_initial_baseline,
                    )
                    if diff_events:
                        logger.info(f"Diff detected {len(diff_events)} change(s) for {alert_key}")

                    # Notify matched users
                    for event in diff_events:
                        for alert in group.alerts:
                            # Verify if user subscribed to this event type
                            if event.event_type not in (alert.alert_types or []):
                                continue

                            # Verify if show matches user filters
                            if not DiffEngine.matches_alert_filters(event.show, alert):
                                continue

                            payload_hash = compute_event_payload_hash(
                                alert.id, platform, event.cinema_id, event.show.show_id, event.event_type
                            )

                            enqueued = await notifier.enqueue(
                                alert=alert,
                                platform=platform,
                                notification_type=event.event_type,
                                show=event.show,
                                payload_hash=payload_hash,
                                summary=event.summary,
                            )
                            if enqueued:
                                self.metrics["notifications_generated"] += 1

                    # Save new snapshot with cinema_states
                    cinema_states = {}
                    for s in new_shows:
                        c_key = f"{s.cinema_id}:{s.date}"
                        if s.available_seats and s.available_seats > 0:
                            cinema_states[c_key] = "SEATS_AVAILABLE"
                        else:
                            cinema_states[c_key] = "OPEN"

                    new_snapshot_data = {
                        "hash": new_hash,
                        "updated_at": datetime.utcnow().isoformat(),
                        "shows": {s.show_id: s.dict() for s in new_shows},
                        "cinema_states": cinema_states,
                    }
                    await update_platform_state_snapshot(
                        session=session,
                        state_id=state.id,
                        snapshot_hash=new_hash,
                        snapshot_data=new_snapshot_data,
                        is_hot=group.is_hot,
                    )

        except Exception as e:
            logger.error(f"Error polling watch group {alert_key}: {e}")
            async with get_db_session() as session:
                st = await get_or_create_platform_state(
                    session=session,
                    alert_key=alert_key,
                    platform=platform,
                    movie_identifier=movie_id,
                    city_identifier=group.city_identifier,
                )
                await record_platform_state_failure(session, st.id)


scheduler = AdaptiveScheduler()
