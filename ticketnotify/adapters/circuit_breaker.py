"""Circuit Breaker for isolating failing platforms and reporting scraper breakage."""

import time
import logging
from enum import Enum
from typing import Callable, Optional, Awaitable

logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    CLOSED = "closed"       # Normal operation
    OPEN = "open"           # Tripped, requests blocked
    HALF_OPEN = "half_open" # Trial probe after cooldown


class PlatformCircuitBreaker:
    def __init__(
        self,
        platform_name: str,
        max_failures: int = 5,
        reset_timeout: float = 120.0,
        on_break_callback: Optional[Callable[[str, str], Awaitable[None]]] = None,
    ):
        self.platform_name = platform_name
        self.max_failures = max_failures
        self.reset_timeout = reset_timeout
        self.on_break_callback = on_break_callback

        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: Optional[float] = None
        self.last_state_change: float = time.time()
        self.last_error_message: Optional[str] = None
        self.last_alert_time: Optional[float] = None
        self.alert_cooldown_seconds: float = 3600.0  # Alert admin at most once per hour per platform

    def can_execute(self) -> bool:
        """Determines if a request should be attempted."""
        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:
            # Check if cooldown has elapsed
            if time.time() - (self.last_failure_time or 0) > self.reset_timeout:
                logger.info(f"Circuit breaker for [{self.platform_name}] entering HALF_OPEN state.")
                self.state = CircuitState.HALF_OPEN
                self.last_state_change = time.time()
                return True
            return False

        if self.state == CircuitState.HALF_OPEN:
            # Allow trial probe
            return True

        return True

    async def record_success(self) -> None:
        """Record successful call."""
        if self.state == CircuitState.HALF_OPEN:
            logger.info(f"Circuit breaker for [{self.platform_name}] recovered to CLOSED state.")
            self.state = CircuitState.CLOSED
            self.failure_count = 0
            self.last_state_change = time.time()
        elif self.state == CircuitState.CLOSED:
            self.failure_count = 0
        self.success_count += 1

    async def record_failure(self, error: Exception) -> None:
        """Record a failure and trip circuit if threshold reached."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        self.last_error_message = str(error)

        logger.warning(
            f"Circuit failure recorded for [{self.platform_name}]: {self.failure_count}/{self.max_failures}. Error: {error}"
        )

        if self.state == CircuitState.HALF_OPEN or self.failure_count >= self.max_failures:
            prev_state = self.state
            self.state = CircuitState.OPEN
            self.last_state_change = time.time()
            logger.error(
                f"🚨 Circuit breaker TRIPPED to OPEN for [{self.platform_name}]! Platform temporarily disabled."
            )

            # Trigger alert to admin if callback provided and was previously closed (rate-limited by cooldown)
            now = time.time()
            can_alert = (
                self.on_break_callback is not None
                and prev_state == CircuitState.CLOSED
                and (self.last_alert_time is None or now - self.last_alert_time >= self.alert_cooldown_seconds)
            )

            if can_alert:
                self.last_alert_time = now
                try:
                    await self.on_break_callback(
                        self.platform_name,
                        f"Scraper broken / API structure changed on {self.platform_name}: {self.last_error_message}"
                    )
                except Exception as cb_err:
                    logger.error(f"Failed to execute on_break_callback for {self.platform_name}: {cb_err}")

    def get_status_dict(self) -> dict:
        return {
            "platform": self.platform_name,
            "state": self.state.value,
            "failure_count": self.failure_count,
            "max_failures": self.max_failures,
            "last_error": self.last_error_message,
            "last_state_change": self.last_state_change,
        }
