"""Distance and radius calculation helpers using Haversine formula."""

import math
from typing import Optional


def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great circle distance between two points on the earth in kilometers."""
    radius_earth_km = 6371.0

    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    
    a = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return radius_earth_km * c


def is_within_radius(
    user_lat: float,
    user_lon: float,
    cinema_lat: Optional[float],
    cinema_lon: Optional[float],
    max_radius_km: float = 20.0,
) -> bool:
    """Check if cinema coordinates fall within the allowed radius."""
    if cinema_lat is None or cinema_lon is None:
        # If cinema coordinates are unknown, do not filter out
        return True
    
    dist = haversine_distance_km(user_lat, user_lon, cinema_lat, cinema_lon)
    return dist <= max_radius_km
