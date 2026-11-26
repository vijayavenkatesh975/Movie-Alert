"""Diff engine detecting booking openings, new shows, seat changes, and price drops with state transitions."""

import hashlib
import json
import logging
from datetime import datetime, date
from enum import Enum
from typing import List, Dict, Any, Optional, Tuple
from pydantic import BaseModel

from ticketnotify.adapters.base import Show, SeatStatus
from ticketnotify.database.models import Alert
from ticketnotify.location.distance import is_within_radius

logger = logging.getLogger(__name__)


class BookingState(str, Enum):
    NOT_OPEN = "NOT_OPEN"
    OPEN = "OPEN"
    SEATS_AVAILABLE = "SEATS_AVAILABLE"


class DiffEvent(BaseModel):
    event_type: str  # bookings_opened, new_show_added, seats_available, seats_filling_fast, price_drop, specific_cinema_opened
    platform: str
    movie_id: str
    movie_title: str
    cinema_id: str
    cinema_name: str
    date: str
    show: Show
    summary: str
    payload_hash: str


def compute_snapshot_hash(shows: List[Show]) -> str:
    """Computes a deterministic hash of a shows list snapshot regardless of show order."""
    if not shows:
        return "empty"
    # Sort show IDs to ensure consistent hash
    keys = sorted([f"{s.show_id}:{s.seat_status}:{s.min_price}:{s.available_seats}" for s in shows])
    raw = "|".join(keys).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def compute_event_payload_hash(alert_id: int, platform: str, cinema_id: str, show_id: str, event_type: str) -> str:
    """Computes deterministic dedupe hash for (alert_id, platform, cinema, show_id, event_type)."""
    raw = f"{alert_id}:{platform.lower()}:{cinema_id}:{show_id}:{event_type}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def determine_cinema_date_state(shows: List[Show]) -> BookingState:
    """Evaluates state for a specific (cinema, date) slice."""
    if not shows:
        return BookingState.NOT_OPEN
    has_available = any(
        s.seat_status in (SeatStatus.AVAILABLE, SeatStatus.FILLING_FAST, SeatStatus.ALMOST_FULL)
        and (s.available_seats is None or s.available_seats > 0)
        for s in shows
    )
    if has_available:
        return BookingState.SEATS_AVAILABLE
    return BookingState.OPEN


class DiffEngine:
    @staticmethod
    def diff(
        old_snapshot: Dict[str, Any],
        new_shows: List[Show],
        platform: str,
        movie_id: str,
        is_initial_baseline: bool = False,
    ) -> List[DiffEvent]:
        """
        Compares old snapshot against new list of Show objects.
        Transitions:
        - NOT_OPEN -> OPEN / SEATS_AVAILABLE => 'bookings_opened'
        - OPEN -> SEATS_AVAILABLE => 'seats_available'
        - Brand new show added => 'new_show_added'
        - Seat status changes => 'seats_filling_fast'
        - Price drops => 'price_drop'
        """
        if is_initial_baseline:
            # First poll silently records baseline, no alert triggers
            return []

        events: List[DiffEvent] = []
        old_shows_dict: Dict[str, Dict[str, Any]] = old_snapshot.get("shows", {})
        old_cinema_states: Dict[str, str] = old_snapshot.get("cinema_states", {})

        # Group new shows by (cinema_id, date)
        new_by_cinema_date: Dict[Tuple[str, str], List[Show]] = {}
        for s in new_shows:
            new_by_cinema_date.setdefault((s.cinema_id, s.date), []).append(s)

        # 1. Evaluate cinema-date level state transitions
        for (c_id, s_date), c_shows in new_by_cinema_date.items():
            state_key = f"{c_id}:{s_date}"
            if state_key in old_cinema_states:
                prev_state_str = old_cinema_states[state_key]
                prev_state = BookingState(prev_state_str) if prev_state_str in BookingState._value2member_map_ else BookingState.NOT_OPEN
            elif any(s.show_id in old_shows_dict for s in c_shows):
                # Cinema/date shows already existed in previous snapshot
                has_prev_available = any(
                    old_shows_dict[s.show_id].get("seat_status") in (
                        SeatStatus.AVAILABLE,
                        SeatStatus.FILLING_FAST,
                        SeatStatus.ALMOST_FULL,
                        "available",
                        "filling_fast",
                        "almost_full",
                    )
                    or (old_shows_dict[s.show_id].get("available_seats") or 0) > 0
                    for s in c_shows
                    if s.show_id in old_shows_dict
                )
                prev_state = BookingState.SEATS_AVAILABLE if has_prev_available else BookingState.OPEN
            else:
                prev_state = BookingState.NOT_OPEN

            curr_state = determine_cinema_date_state(c_shows)

            first_show = c_shows[0]

            # Transition: NOT_OPEN -> OPEN or SEATS_AVAILABLE
            if prev_state == BookingState.NOT_OPEN and curr_state in (BookingState.OPEN, BookingState.SEATS_AVAILABLE):
                events.append(
                    DiffEvent(
                        event_type="bookings_opened",
                        platform=platform,
                        movie_id=movie_id,
                        movie_title=first_show.movie_title,
                        cinema_id=c_id,
                        cinema_name=first_show.cinema_name,
                        date=s_date,
                        show=first_show,
                        summary=f"Bookings opened for {first_show.movie_title} at {first_show.cinema_name} ({s_date}) on {platform.upper()}!",
                        payload_hash=f"opened:{platform}:{c_id}:{s_date}",
                    )
                )

            # Transition: OPEN (sold out) -> SEATS_AVAILABLE
            elif prev_state == BookingState.OPEN and curr_state == BookingState.SEATS_AVAILABLE:
                events.append(
                    DiffEvent(
                        event_type="seats_available",
                        platform=platform,
                        movie_id=movie_id,
                        movie_title=first_show.movie_title,
                        cinema_id=c_id,
                        cinema_name=first_show.cinema_name,
                        date=s_date,
                        show=first_show,
                        summary=f"Seats now available for {first_show.movie_title} at {first_show.cinema_name} ({s_date})!",
                        payload_hash=f"seats_avail:{platform}:{c_id}:{s_date}",
                    )
                )

        # 2. Evaluate individual show additions and changes
        for new_show in new_shows:
            show_key = new_show.show_id

            if show_key not in old_shows_dict:
                # Brand new show added
                events.append(
                    DiffEvent(
                        event_type="new_show_added",
                        platform=platform,
                        movie_id=movie_id,
                        movie_title=new_show.movie_title,
                        cinema_id=new_show.cinema_id,
                        cinema_name=new_show.cinema_name,
                        date=new_show.date,
                        show=new_show,
                        summary=f"New show added at {new_show.cinema_name} ({new_show.date} {new_show.time}, {new_show.format})",
                        payload_hash=f"new_show:{show_key}",
                    )
                )
            else:
                old_data = old_shows_dict[show_key]
                old_status = old_data.get("seat_status")
                old_price = old_data.get("min_price")

                # Check seats filling fast
                if (
                    old_status == SeatStatus.AVAILABLE
                    and new_show.seat_status in [SeatStatus.FILLING_FAST, SeatStatus.ALMOST_FULL]
                ):
                    events.append(
                        DiffEvent(
                            event_type="seats_filling_fast",
                            platform=platform,
                            movie_id=movie_id,
                            movie_title=new_show.movie_title,
                            cinema_id=new_show.cinema_id,
                            cinema_name=new_show.cinema_name,
                            date=new_show.date,
                            show=new_show,
                            summary=f"Seats filling fast at {new_show.cinema_name} ({new_show.time})!",
                            payload_hash=f"filling_fast:{show_key}",
                        )
                    )

                # Check price drop
                if old_price is not None and new_show.min_price is not None:
                    if float(new_show.min_price) < float(old_price):
                        events.append(
                            DiffEvent(
                                event_type="price_drop",
                                platform=platform,
                                movie_id=movie_id,
                                cinema_id=new_show.cinema_id,
                                cinema_name=new_show.cinema_name,
                                date=new_show.date,
                                movie_title=new_show.movie_title,
                                show=new_show,
                                summary=f"Price dropped from {old_price} to {new_show.min_price} at {new_show.cinema_name}!",
                                payload_hash=f"price_drop:{show_key}:{new_show.min_price}",
                            )
                        )

        return events

    @staticmethod
    def matches_alert_filters(show: Show, alert: Alert) -> bool:
        """Evaluates whether a Show satisfies the user's alert filters."""
        filters: Dict[str, Any] = alert.filters_json or {}

        # 1. Date Range Filter
        date_range = filters.get("date_range")
        if date_range and isinstance(date_range, list) and len(date_range) >= 1:
            try:
                show_d = datetime.strptime(show.date, "%Y-%m-%d").date()
                start_d = datetime.strptime(date_range[0], "%Y-%m-%d").date()
                if show_d < start_d:
                    return False
                if len(date_range) >= 2 and date_range[1]:
                    end_d = datetime.strptime(date_range[1], "%Y-%m-%d").date()
                    if show_d > end_d:
                        return False
            except Exception:
                pass

        # 2. Language Filter
        allowed_langs = [l.lower() for l in filters.get("languages", []) if l]
        if allowed_langs and show.language:
            if not any(al in show.language.lower() for al in allowed_langs):
                return False

        # 3. Format Filter (2D, 3D, IMAX, 4DX, etc.)
        allowed_formats = [f.lower() for f in filters.get("formats", []) if f]
        if allowed_formats and show.format:
            if not any(af in show.format.lower() for af in allowed_formats):
                return False

        # 4. Cinema Chains Filter (PVR, INOX, Cinepolis, etc.)
        preferred_chains = [c.lower() for c in filters.get("chains", []) if c]
        if preferred_chains:
            chain_match = False
            if show.cinema_chain and show.cinema_chain.lower() in preferred_chains:
                chain_match = True
            elif any(pc in show.cinema_name.lower() for pc in preferred_chains):
                chain_match = True
            if not chain_match:
                return False

        # 5. Max Price Filter
        max_price = filters.get("max_price")
        if max_price is not None and show.min_price is not None:
            if float(show.min_price) > float(max_price):
                return False

        # 6. Minimum Seats Needed Filter
        min_seats = filters.get("min_seats") or alert.seats_needed
        if min_seats is not None and show.available_seats is not None:
            if show.available_seats < int(min_seats):
                return False

        # 7. Radius filter from user location
        if alert.location:
            user_lat = alert.location.latitude
            user_lng = alert.location.longitude
            radius_km = alert.location.radius_km or 20.0
            if not is_within_radius(user_lat, user_lng, show.latitude, show.longitude, radius_km):
                return False

        # 8. Selected Theatres Filter
        if alert.selected_cinemas and isinstance(alert.selected_cinemas, dict):
            plat_cinemas = alert.selected_cinemas.get(show.platform) or alert.selected_cinemas.get("platform_cinema_ids", {}).get(show.platform)
            canonical_names = alert.selected_cinemas.get("names", [])
            
            if plat_cinemas:
                if show.cinema_id not in plat_cinemas and not any(cn.lower() in show.cinema_name.lower() for cn in canonical_names):
                    return False

        return True
