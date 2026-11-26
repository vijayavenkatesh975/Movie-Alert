"""Location module."""
from ticketnotify.location.models import NormalizedLocation
from ticketnotify.location.geocoder import geocoder, LocationGeocoder
from ticketnotify.location.matcher import map_location_to_platforms, PLATFORM_OPERATING_COUNTRIES
from ticketnotify.location.distance import haversine_distance_km, is_within_radius

__all__ = [
    "NormalizedLocation",
    "geocoder",
    "LocationGeocoder",
    "map_location_to_platforms",
    "PLATFORM_OPERATING_COUNTRIES",
    "haversine_distance_km",
    "is_within_radius",
]
