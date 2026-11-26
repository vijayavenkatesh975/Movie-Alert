"""Central adapter registry with circuit breakers and resilience management."""

import logging
from typing import Dict, List, Optional, Callable, Awaitable, Any

from ticketnotify.config import settings
from ticketnotify.location.models import NormalizedLocation
from ticketnotify.adapters.base import (
    PlatformAdapter,
    MovieMatch,
    Show,
    FetchResult,
    FetchStatus,
    classify_fetch_error,
)
from ticketnotify.adapters.circuit_breaker import PlatformCircuitBreaker, CircuitState
from ticketnotify.adapters.bms import BookMyShowAdapter
from ticketnotify.adapters.ticketnew import TicketnewAdapter
from ticketnotify.adapters.district import DistrictAdapter
from ticketnotify.adapters.pvrinox import PvrInoxAdapter

logger = logging.getLogger(__name__)


class AdapterRegistry:
    def __init__(self):
        self._adapters: Dict[str, PlatformAdapter] = {}
        self._circuit_breakers: Dict[str, PlatformCircuitBreaker] = {}
        self._admin_alert_callback: Optional[Callable[[str, str], Awaitable[None]]] = None

    def set_admin_alert_callback(self, callback: Callable[[str, str], Awaitable[None]]) -> None:
        """Register callback for scraper broken / circuit breaker alerts to admin."""
        self._admin_alert_callback = callback
        for cb in self._circuit_breakers.values():
            cb.on_break_callback = callback

    def register(self, adapter: PlatformAdapter) -> None:
        """Register a platform adapter with its dedicated circuit breaker."""
        name = adapter.platform_name.lower()
        self._adapters[name] = adapter
        self._circuit_breakers[name] = PlatformCircuitBreaker(
            platform_name=name,
            max_failures=settings.CIRCUIT_BREAKER_MAX_FAILURES,
            reset_timeout=float(settings.CIRCUIT_BREAKER_RESET_TIMEOUT),
            on_break_callback=self._admin_alert_callback,
        )
        logger.info(f"Registered platform adapter: [{name}] ({adapter.platform_label})")

    def get_adapter(self, name: str) -> Optional[PlatformAdapter]:
        return self._adapters.get(name.lower())

    def get_all_adapters(self) -> Dict[str, PlatformAdapter]:
        return dict(self._adapters)

    def get_supported_adapters(self, location: NormalizedLocation) -> List[PlatformAdapter]:
        """Returns adapters that operate in the given location's country."""
        return [
            adapter for adapter in self._adapters.values()
            if adapter.is_location_supported(location)
        ]

    def is_platform_available(self, name: str) -> bool:
        """Check if platform exists and circuit breaker is not open."""
        cb = self._circuit_breakers.get(name.lower())
        if not cb:
            return False
        return cb.can_execute()

    async def search_movie(
        self,
        platform_name: str,
        title: str,
        location: NormalizedLocation,
    ) -> List[MovieMatch]:
        """Search movie on a specific platform through its circuit breaker."""
        adapter = self.get_adapter(platform_name)
        cb = self._circuit_breakers.get(platform_name.lower())

        if not adapter or not cb:
            logger.warning(f"Adapter not found for platform: {platform_name}")
            return []

        if not cb.can_execute():
            logger.warning(f"Circuit breaker for [{platform_name}] is OPEN. Skipping search.")
            return []

        try:
            results = await adapter.search_movie(title, location)
            await cb.record_success()
            return results
        except Exception as e:
            await cb.record_failure(e)
            logger.error(f"Error searching on platform [{platform_name}]: {e}")
            return []

    async def get_shows(
        self,
        platform_name: str,
        movie_id: str,
        location: NormalizedLocation,
        target_date: Optional[str] = None,
    ) -> FetchResult:
        """Fetch shows for movie on a platform through its circuit breaker."""
        adapter = self.get_adapter(platform_name)
        cb = self._circuit_breakers.get(platform_name.lower())

        if not adapter or not cb:
            return FetchResult.unavailable(f"Adapter not registered for platform: {platform_name}")

        if not cb.can_execute():
            logger.warning(f"Circuit breaker for [{platform_name}] is OPEN. Skipping get_shows.")
            return FetchResult.unavailable(f"Circuit breaker for [{platform_name}] is OPEN")

        try:
            res = await adapter.get_shows(movie_id, location, target_date)
            # Ensure it is a FetchResult
            if isinstance(res, FetchResult):
                if res.is_success:
                    await cb.record_success()
                else:
                    await cb.record_failure(Exception(res.error_message or "Platform fetch failure"))
                return res
            else:
                await cb.record_success()
                return FetchResult.ok(res)
        except Exception as e:
            await cb.record_failure(e)
            logger.error(f"Error fetching shows on platform [{platform_name}]: {e}")
            return classify_fetch_error(e)

    async def health_check_all(self) -> Dict[str, bool]:
        """Runs health check on all adapters."""
        health: Dict[str, bool] = {}
        for name, adapter in self._adapters.items():
            try:
                is_ok = await adapter.health_check()
                health[name] = is_ok
            except Exception:
                health[name] = False
        return health

    def get_circuit_statuses(self) -> List[dict]:
        """Returns circuit breaker status list for all platforms."""
        return [cb.get_status_dict() for cb in self._circuit_breakers.values()]


# Create and initialize global registry
registry = AdapterRegistry()
registry.register(BookMyShowAdapter())
registry.register(TicketnewAdapter())
registry.register(DistrictAdapter())
registry.register(PvrInoxAdapter())
