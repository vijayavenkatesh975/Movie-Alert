"""Adapters package."""

from ticketnotify.adapters.base import PlatformAdapter, MovieMatch, Show, SeatStatus
from ticketnotify.adapters.registry import registry, AdapterRegistry
from ticketnotify.adapters.circuit_breaker import PlatformCircuitBreaker, CircuitState
from ticketnotify.adapters.bms import BookMyShowAdapter
from ticketnotify.adapters.ticketnew import TicketnewAdapter
from ticketnotify.adapters.district import DistrictAdapter
from ticketnotify.adapters.pvrinox import PvrInoxAdapter

__all__ = [
    "PlatformAdapter",
    "MovieMatch",
    "Show",
    "SeatStatus",
    "registry",
    "AdapterRegistry",
    "PlatformCircuitBreaker",
    "CircuitState",
    "BookMyShowAdapter",
    "TicketnewAdapter",
    "DistrictAdapter",
    "PvrInoxAdapter",
]
