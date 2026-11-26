"""SQLAlchemy declarative models for TicketNotify."""

from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy import (
    Column,
    Integer,
    BigInteger,
    String,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    JSON,
    Index,
    Text,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False, index=True)
    username = Column(String(255), nullable=True)
    first_name = Column(String(255), nullable=True)
    language = Column(String(10), default="en", nullable=False)
    
    # Default location reference
    default_location_id = Column(Integer, ForeignKey("locations.id", ondelete="SET NULL"), nullable=True)
    
    # Quiet hours: 24h format e.g. 23 (11 PM) to 7 (7 AM)
    quiet_hours_enabled = Column(Boolean, default=False, nullable=False)
    quiet_hours_start = Column(Integer, default=23, nullable=False)
    quiet_hours_end = Column(Integer, default=7, nullable=False)
    
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    locations = relationship("Location", back_populates="user", foreign_keys="Location.user_id", cascade="all, delete-orphan")
    alerts = relationship("Alert", back_populates="user", cascade="all, delete-orphan")
    notifications = relationship("NotificationLog", back_populates="user", cascade="all, delete-orphan")


class Location(Base):
    __tablename__ = "locations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)  # User's label e.g. "Home", "Office", or city name
    
    # Normalized location components
    normalized_city = Column(String(120), nullable=False, index=True)
    normalized_country = Column(String(120), nullable=False, index=True)
    country_code = Column(String(10), nullable=False)
    state = Column(String(120), nullable=True)
    
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    radius_km = Column(Float, default=20.0, nullable=False)  # Radius filter for cinemas
    
    # Pre-calculated platform-specific region/city codes e.g. {"bms": "BANG", "ticketnew": "chennai"}
    platform_mappings = Column(JSON, default=dict, nullable=False)
    
    is_default = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Helper properties for adapter compatibility
    @property
    def platform_codes(self) -> Dict[str, Any]:
        return self.platform_mappings or {}

    @property
    def city(self) -> str:
        return self.normalized_city

    @property
    def country(self) -> str:
        return self.normalized_country

    # Relationships
    user = relationship("User", back_populates="locations", foreign_keys=[user_id])
    alerts = relationship("Alert", back_populates="location")


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    movie_query = Column(String(255), nullable=False, index=True)
    
    # Discovered platform-specific movie IDs: {"bms": "ET001234", "ticketnew": "4321", "pvrinox": "HO123"}
    movie_ids_by_platform = Column(JSON, default=dict, nullable=False)
    
    location_id = Column(Integer, ForeignKey("locations.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Active platforms for this alert e.g. ["bms", "ticketnew", "pvrinox", "district"]
    platforms = Column(JSON, default=list, nullable=False)
    
    # Selected cinemas filter: {"canonical_ids": [...], "platform_cinema_ids": {"bms": ["PVR01"], ...}}
    # If empty or not set, alerts trigger for all cinemas in the radius
    selected_cinemas = Column(JSON, default=dict, nullable=False)

    # Seat preference fields
    seats_needed = Column(Integer, default=1, nullable=False)
    must_be_consecutive = Column(Boolean, default=True, nullable=False)
    row_zone = Column(String(20), default="any", nullable=False)  # front | middle | back | any
    column_zone = Column(String(20), default="any", nullable=False)  # center | left | right | corner | aisle | any
    seat_category = Column(String(50), default="any", nullable=False)  # Recliner | Premium | Gold | Silver | any
    max_price_per_seat = Column(Float, nullable=True)

    # Urgency tier: "HOT" (1-3s), "WARM" (10-15s), "COLD" (1-2 min)
    urgency = Column(String(20), default="WARM", nullable=False)
    
    # Detailed filter criteria:
    # {
    #   "date_range": ["2026-11-25", "2026-11-28"],
    #   "languages": ["Tamil", "English", "Hindi"],
    #   "formats": ["IMAX 3D", "4DX", "2D"],
    #   "chains": ["PVR", "INOX", "Cinepolis"],
    #   "time_window": {"start": "18:00", "end": "23:59"},
    #   "max_price": 500,
    #   "min_seats": 2
    # }
    filters_json = Column(JSON, default=dict, nullable=False)
    
    # Subscribed alert triggers:
    # ["bookings_opened", "new_show_added", "seats_filling_fast", "price_drop", "specific_cinema_opened"]
    alert_types = Column(JSON, default=list, nullable=False)
    
    # Status: "active", "paused", "deleted"
    status = Column(String(20), default="active", nullable=False, index=True)
    is_muted = Column(Boolean, default=False, nullable=False)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("User", back_populates="alerts")
    location = relationship("Location", back_populates="alerts")
    notifications = relationship("NotificationLog", back_populates="alert", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_alert_status_user", "status", "user_id"),
    )


class PlatformState(Base):
    """
    Tracks state of a specific movie watch per platform and city.
    Shared across users who track the same movie+city+platform to achieve 1:N deduplication.
    """
    __tablename__ = "platform_state"

    id = Column(Integer, primary_key=True, autoincrement=True)
    alert_key = Column(String(255), nullable=False, index=True)  # e.g. "bms:bangalore:ET001234"
    platform = Column(String(50), nullable=False, index=True)
    movie_identifier = Column(String(255), nullable=False)
    city_identifier = Column(String(120), nullable=False)
    
    last_snapshot_hash = Column(String(64), nullable=True)
    last_snapshot_data = Column(JSON, default=dict, nullable=False)
    
    last_checked_at = Column(DateTime, nullable=True)
    check_count = Column(Integer, default=0, nullable=False)
    consecutive_failures = Column(Integer, default=0, nullable=False)
    is_hot = Column(Boolean, default=False, nullable=False)  # If True, polled at hot interval
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("idx_state_key_platform", "alert_key", "platform", unique=True),
    )


class NotificationLog(Base):
    """Log of every notification sent to prevent repeat spam."""
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    alert_id = Column(Integer, ForeignKey("alerts.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    platform = Column(String(50), nullable=False)
    
    notification_type = Column(String(50), nullable=False)  # bookings_opened, new_show_added, etc.
    show_key = Column(String(255), nullable=True)  # unique ID of cinema + time + format
    payload_hash = Column(String(64), nullable=False, index=True)
    message_text = Column(Text, nullable=True)
    
    sent_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    alert = relationship("Alert", back_populates="notifications")
    user = relationship("User", back_populates="notifications")

    __table_args__ = (
        Index("idx_notification_dedup", "alert_id", "platform", "payload_hash"),
    )
