"""Proxy manager with health scoring, sticky sessions, automatic retry and retirement."""

import logging
import os
import time
from dataclasses import dataclass
from typing import Dict, List, Optional
import httpx

from ticketnotify.config import settings

logger = logging.getLogger(__name__)


@dataclass
class ProxyNode:
    url: str
    success_count: int = 0
    failure_count: int = 0
    consecutive_failures: int = 0
    total_latency_ms: float = 0.0
    is_active: bool = True
    last_failure_time: float = 0.0

    @property
    def avg_latency_ms(self) -> float:
        if self.success_count == 0:
            return 999.0
        return self.total_latency_ms / float(self.success_count)

    @property
    def health_score(self) -> float:
        """Higher is better."""
        if not self.is_active:
            return -1.0
        total = self.success_count + self.failure_count
        if total == 0:
            return 100.0
        success_rate = (self.success_count / float(total)) * 100.0
        latency_factor = max(0.0, 50.0 - (self.avg_latency_ms / 50.0))
        return success_rate + latency_factor


class ProxyManager:
    def __init__(self):
        self._proxies: Dict[str, ProxyNode] = {}
        self._platform_sticky: Dict[str, str] = {}
        self._load_proxies()

    def _load_proxies(self) -> None:
        raw = os.environ.get("PROXY_URLS") or getattr(settings, "PROXY_URLS", "")
        if raw:
            for item in raw.split(","):
                u = item.strip()
                if u:
                    self._proxies[u] = ProxyNode(url=u)

        if not self._proxies:
            # Check parsed list from settings
            for u in getattr(settings, "proxy_list_parsed", []):
                self._proxies[u] = ProxyNode(url=u)

    def get_proxy(self, platform_name: Optional[str] = None) -> Optional[str]:
        """
        Returns a healthy proxy URL, preferring sticky proxy for the platform.
        Returns None (direct connection) if no proxies are configured or available.
        """
        now = time.time()
        # Revive proxies retired > 300s (5 min) ago
        for p in self._proxies.values():
            if not p.is_active and (now - p.last_failure_time) > 300.0:
                p.is_active = True
                p.consecutive_failures = 0
                logger.info(f"Reviving proxy after cooldown: {p.url}")

        active_nodes = [p for p in self._proxies.values() if p.is_active]
        if not active_nodes:
            if self._proxies:
                logger.warning("All proxies in pool are currently retired! Falling back to direct connection.")
            return None

        # Check sticky proxy for this platform
        if platform_name and platform_name in self._platform_sticky:
            sticky_url = self._platform_sticky[platform_name]
            node = self._proxies.get(sticky_url)
            if node and node.is_active:
                return sticky_url

        # Pick proxy with highest health score
        active_nodes.sort(key=lambda n: n.health_score, reverse=True)
        chosen = active_nodes[0].url

        if platform_name:
            self._platform_sticky[platform_name] = chosen

        return chosen

    def report_result(self, proxy_url: Optional[str], success: bool, latency_ms: float = 0.0) -> None:
        if not proxy_url or proxy_url not in self._proxies:
            return

        node = self._proxies[proxy_url]
        if success:
            node.success_count += 1
            node.consecutive_failures = 0
            node.total_latency_ms += latency_ms
        else:
            node.failure_count += 1
            node.consecutive_failures += 1
            node.last_failure_time = time.time()
            if node.consecutive_failures >= 3:
                node.is_active = False
                logger.warning(f"Retiring unhealthy proxy: {proxy_url} (3 consecutive failures)")

    def add_proxy(self, url: str) -> None:
        if url not in self._proxies:
            self._proxies[url] = ProxyNode(url=url)


proxy_manager = ProxyManager()
