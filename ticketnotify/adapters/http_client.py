"""Resilient HTTP client with HTTP/2 keep-alive, User-Agent rotation, and proxy management."""

import asyncio
import logging
import random
import time
from typing import Optional, Dict, Any
import httpx

from ticketnotify.config import settings
from ticketnotify.adapters.proxy_manager import proxy_manager

logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.5; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 14; SM-S928B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.6422.113 Mobile Safari/537.36",
]


class ResilientHttpClient:
    def __init__(self):
        self.timeout = settings.SCRAPER_REQUEST_TIMEOUT
        self._shared_clients: Dict[Optional[str], httpx.AsyncClient] = {}

    def get_random_user_agent(self) -> str:
        return random.choice(USER_AGENTS)

    def _get_client_for_proxy(self, proxy_url: Optional[str]) -> httpx.AsyncClient:
        """Maintains persistent HTTP/2 (or HTTP/1.1 fallback) keep-alive clients per proxy endpoint."""
        if proxy_url not in self._shared_clients or self._shared_clients[proxy_url].is_closed:
            limits = httpx.Limits(max_keepalive_connections=20, max_connections=50, keepalive_expiry=60.0)
            timeout = httpx.Timeout(self.timeout, connect=5.0)
            try:
                import h2  # Check if h2 is importable
                self._shared_clients[proxy_url] = httpx.AsyncClient(
                    timeout=timeout,
                    proxy=proxy_url,
                    follow_redirects=True,
                    http2=True,
                    limits=limits,
                )
            except Exception:
                self._shared_clients[proxy_url] = httpx.AsyncClient(
                    timeout=timeout,
                    proxy=proxy_url,
                    follow_redirects=True,
                    http2=False,
                    limits=limits,
                )
        return self._shared_clients[proxy_url]

    async def get_json(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        platform_name: Optional[str] = None,
        jitter_range: tuple[float, float] = (0.05, 0.2),
    ) -> Any:
        """Executes GET request with HTTP/2 keep-alive, jitter, and proxy health tracking."""
        if jitter_range[1] > 0:
            delay = random.uniform(jitter_range[0], jitter_range[1])
            await asyncio.sleep(delay)

        req_headers = {
            "User-Agent": self.get_random_user_agent(),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
        }
        if headers:
            req_headers.update(headers)

        proxy_url = proxy_manager.get_proxy(platform_name)
        client = self._get_client_for_proxy(proxy_url)
        t0 = time.time()

        try:
            resp = await client.get(url, params=params, headers=req_headers)
            resp.raise_for_status()
            elapsed_ms = (time.time() - t0) * 1000.0
            proxy_manager.report_result(proxy_url, success=True, latency_ms=elapsed_ms)
            return resp.json()
        except Exception as e:
            elapsed_ms = (time.time() - t0) * 1000.0
            proxy_manager.report_result(proxy_url, success=False, latency_ms=elapsed_ms)
            raise e

    async def post_json(
        self,
        url: str,
        json_data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        platform_name: Optional[str] = None,
        jitter_range: tuple[float, float] = (0.05, 0.2),
    ) -> Any:
        """Executes POST request with HTTP/2 keep-alive and proxy health tracking."""
        if jitter_range[1] > 0:
            delay = random.uniform(jitter_range[0], jitter_range[1])
            await asyncio.sleep(delay)

        req_headers = {
            "User-Agent": self.get_random_user_agent(),
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
        }
        if headers:
            req_headers.update(headers)

        proxy_url = proxy_manager.get_proxy(platform_name)
        client = self._get_client_for_proxy(proxy_url)
        t0 = time.time()

        try:
            resp = await client.post(url, json=json_data, headers=req_headers)
            resp.raise_for_status()
            elapsed_ms = (time.time() - t0) * 1000.0
            proxy_manager.report_result(proxy_url, success=True, latency_ms=elapsed_ms)
            return resp.json()
        except Exception as e:
            elapsed_ms = (time.time() - t0) * 1000.0
            proxy_manager.report_result(proxy_url, success=False, latency_ms=elapsed_ms)
            raise e

    async def close(self) -> None:
        """Closes all underlying HTTP clients."""
        for client in self._shared_clients.values():
            if not client.is_closed:
                await client.aclose()
        self._shared_clients.clear()


http_client = ResilientHttpClient()
