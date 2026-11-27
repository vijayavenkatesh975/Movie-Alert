"""Unit tests for FastAPI endpoints: /health, /ready, /metrics, /api/admin/status."""

import json
from contextlib import asynccontextmanager
from unittest.mock import patch
import pytest
from ticketnotify.api.app import health_check, readiness_check, platform_status, prometheus_metrics, admin_status_api
from ticketnotify.config import settings
from ticketnotify.adapters.registry import registry


class MockDBSession:
    async def scalar(self, *args, **kwargs):
        return 0


@asynccontextmanager
async def mock_get_db_session():
    yield MockDBSession()


async def mock_health_check_all():
    return {
        "bms": True,
        "ticketnew": True,
        "district": True,
        "pvrinox": True,
    }


async def mock_check_redis_health():
    return True, "connected (mock_redis)"


def test_health_and_metrics_endpoints():
    settings.TESTING = True

    def _drive(coro):
        try:
            coro.send(None)
        except StopIteration as e:
            return e.value

    with patch("ticketnotify.api.app.get_db_session", mock_get_db_session), \
         patch("ticketnotify.api.app.check_redis_health", mock_check_redis_health), \
         patch.object(registry, "health_check_all", mock_health_check_all):

        # 1. Test /health (cheap, no DB hits)
        health_resp = _drive(health_check())
        assert health_resp["status"] == "healthy"
        assert health_resp["service"] == "TicketNotify"

        # 2. Test /ready (readiness probe)
        ready_resp = _drive(readiness_check())
        assert ready_resp.status_code == 200
        ready_data = json.loads(ready_resp.body.decode("utf-8"))
        assert ready_data["status"] == "ready"
        assert ready_data["database"] == "connected"

        # 3. Test /api/platforms/status
        plat_data = _drive(platform_status())
        assert "platforms" in plat_data
        assert "circuit_breakers" in plat_data

        # 4. Test /metrics
        metrics_resp = _drive(prometheus_metrics())
        assert metrics_resp.status_code == 200
        metrics_text = metrics_resp.body.decode("utf-8")
        assert "ticketnotify_active_users" in metrics_text
        assert "ticketnotify_active_alerts" in metrics_text
        assert "ticketnotify_poll_latency_ms" in metrics_text

        # 5. Test /api/admin/status
        admin_data = _drive(admin_status_api())
        assert "users" in admin_data
        assert "active_alerts" in admin_data
        assert "scheduler_metrics" in admin_data

    settings.TESTING = False
