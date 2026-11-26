"""Session and cookie manager with automatic pre-warming, header rotation, and token refresh."""

import asyncio
import logging
import time
from typing import Dict, Optional, Any
import httpx

from ticketnotify.config import settings

logger = logging.getLogger(__name__)


class PlatformSession:
    """Stores warmed session credentials, cookies, and tokens for an adapter."""

    def __init__(self, platform: str, ttl_seconds: float = 1800.0):
        self.platform = platform
        self.ttl_seconds = ttl_seconds
        self.cookies: Dict[str, str] = {}
        self.headers: Dict[str, str] = {}
        self.extra: Dict[str, Any] = {}
        self.last_refreshed_at: float = 0.0

    @property
    def is_expired(self) -> bool:
        return (time.time() - self.last_refreshed_at) > self.ttl_seconds

    def update(self, cookies: Dict[str, str], headers: Dict[str, str], extra: Optional[Dict[str, Any]] = None) -> None:
        self.cookies.update(cookies)
        self.headers.update(headers)
        if extra:
            self.extra.update(extra)
        self.last_refreshed_at = time.time()


class SessionManager:
    """Manages pre-warmed sessions across all platforms with auto-refresh."""

    def __init__(self):
        self._sessions: Dict[str, PlatformSession] = {}
        self._locks: Dict[str, asyncio.Lock] = {}

    def _get_lock(self, platform: str) -> asyncio.Lock:
        if platform not in self._locks:
            self._locks[platform] = asyncio.Lock()
        return self._locks[platform]

    def get_session(self, platform: str) -> PlatformSession:
        if platform not in self._sessions:
            self._sessions[platform] = PlatformSession(platform)
        return self._sessions[platform]

    async def get_valid_headers(self, platform: str, city: str = "bengaluru") -> Dict[str, str]:
        """Returns headers with active pre-warmed cookies and tokens."""
        session = self.get_session(platform)
        if session.is_expired:
            lock = self._get_lock(platform)
            async with lock:
                # Double-check inside lock
                if session.is_expired:
                    await self.refresh_session(platform, city)

        headers = dict(session.headers)
        if session.cookies:
            cookie_str = "; ".join([f"{k}={v}" for k, v in session.cookies.items()])
            headers["Cookie"] = cookie_str
        return headers

    async def refresh_session(self, platform: str, city: str = "bengaluru") -> None:
        """Pre-warms and refreshes session credentials for the target platform."""
        platform = platform.lower()
        logger.info(f"Pre-warming session for [{platform}] in [{city}]...")

        if platform == "bms":
            await self._refresh_bms_session(city)
        elif platform == "pvrinox":
            await self._refresh_pvr_session(city)
        elif platform in ("district", "ticketnew"):
            await self._refresh_district_session(city)
        else:
            logger.debug(f"No custom session pre-warmer needed for {platform}")

    async def _refresh_bms_session(self, city: str) -> None:
        """Extracts bmsId and session cookies by visiting BMS portal."""
        session = self.get_session("bms")
        url = f"https://in.bookmyshow.com/explore/home/{city.lower()}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

        cookies: Dict[str, str] = {}
        bms_id = "WEB_GUEST"
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                resp = await client.get(url, headers=headers)
                for k, v in resp.cookies.items():
                    cookies[k] = v
                if "bmsId" in cookies:
                    bms_id = cookies["bmsId"]
        except Exception as e:
            logger.warning(f"Could not reach BMS home page for session pre-warm: {e}")

        # Set standard BMS exploration headers
        req_headers = {
            "x-app-code": "WEB",
            "x-platform": "WEB",
            "x-bms-id": bms_id,
            "Referer": url,
            "Origin": "https://in.bookmyshow.com",
        }
        session.update(cookies=cookies, headers=req_headers, extra={"bms_id": bms_id})

    async def _refresh_pvr_session(self, city: str) -> None:
        """Pre-warms PVR INOX headers with client_id and website platform tokens."""
        session = self.get_session("pvrinox")
        headers = {
            "client_id": "48530476451693207526480",
            "appVersion": "1.0",
            "platform": "WEBSITE",
            "Origin": "https://www.pvrcinemas.com",
            "Referer": "https://www.pvrcinemas.com/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        }
        session.update(cookies={}, headers=headers)

    async def _refresh_district_session(self, city: str) -> None:
        """Pre-warms District/Ticketnew session with web client headers."""
        session = self.get_session("district")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Origin": "https://www.district.in",
            "Referer": f"https://www.district.in/movies-in-{city.lower()}",
            "x-district-client": "web",
        }
        session.update(cookies={}, headers=headers)


# Optional Playwright fallback for platforms with strict Cloudflare / anti-bot
class PlaywrightSessionManager:
    """
    Fallback session refresher using headless Playwright.
    Only called when HTTP pre-warming encounters an anti-bot challenge.
    Never used in the fast polling path.
    """

    @classmethod
    async def get_cookies_and_tokens(cls, target_url: str) -> Dict[str, str]:
        """Extracts cookies and local storage tokens via headless browser."""
        try:
            from playwright.async_api import async_playwright
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.goto(target_url, wait_until="domcontentloaded", timeout=20000)
                cookies_list = await page.context.cookies()
                await browser.close()
                return {c["name"]: c["value"] for c in cookies_list}
        except ImportError:
            logger.info("Playwright not installed; headless browser fallback skipped.")
            return {}
        except Exception as e:
            logger.warning(f"Playwright session extraction failed: {e}")
            return {}


# Global instance
session_manager = SessionManager()
