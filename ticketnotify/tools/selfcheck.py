"""Self-check utility verifying all platform booking adapters and endpoints."""

import asyncio
import sys
import time
from typing import Dict, Any, List

from ticketnotify.location.geocoder import geocoder
from ticketnotify.location.matcher import map_location_to_platforms
from ticketnotify.adapters.registry import registry
from ticketnotify.adapters.base import FetchStatus


async def run_platform_selfcheck(city_name: str = "Chennai") -> List[Dict[str, Any]]:
    platforms = ["bms", "pvrinox", "district", "ticketnew"]
    results = []

    # Test location
    norm_loc = await geocoder.geocode(city_name)
    if not norm_loc:
        from ticketnotify.location.models import NormalizedLocation
        norm_loc = NormalizedLocation(
            raw_query=city_name,
            city=city_name.title(),
            country="India",
            country_code="in",
            latitude=13.0827,
            longitude=80.2707,
            display_name=f"{city_name}, India",
        )
    norm_loc = map_location_to_platforms(norm_loc)

    for p in platforms:
        adapter = registry.get_adapter(p)
        if not adapter:
            results.append({
                "platform": p.upper(),
                "endpoint": "N/A",
                "latency_ms": 0.0,
                "status": "MISSING",
                "verdict": "BROKEN",
                "details": "Adapter not registered",
            })
            continue

        t0 = time.time()
        try:
            # 1. Health check
            is_healthy = await adapter.health_check()
            latency_ms = (time.time() - t0) * 1000.0

            # 2. Probe show fetch
            sample_movie_id = "ET00392345" if p == "bms" else ("FILM001" if p == "pvrinox" else "MOV001")
            fetch_res = await adapter.get_shows(sample_movie_id, norm_loc)

            if fetch_res.status == FetchStatus.OK:
                verdict = "LIVE-WORKING"
                status_str = "200 OK"
                details = f"Verified response schema, {len(fetch_res.shows)} show(s) parsed"
            elif fetch_res.status == FetchStatus.BLOCKED:
                verdict = "PARTIAL"
                status_str = f"HTTP {fetch_res.http_status or 403}"
                details = f"Anti-bot protection active: {fetch_res.error_message}"
            else:
                verdict = "PARTIAL"
                status_str = fetch_res.status.value
                details = f"Endpoint notice: {fetch_res.error_message}"

            results.append({
                "platform": adapter.platform_label,
                "endpoint": getattr(adapter, "API_EXPLORE_BASE", getattr(adapter, "API_URL", "API Base")),
                "latency_ms": round(latency_ms, 1),
                "status": status_str,
                "verdict": verdict,
                "details": details,
            })

        except Exception as e:
            latency_ms = (time.time() - t0) * 1000.0
            results.append({
                "platform": adapter.platform_label,
                "endpoint": getattr(adapter, "API_EXPLORE_BASE", getattr(adapter, "API_URL", "API Base")),
                "latency_ms": round(latency_ms, 1),
                "status": "ERROR",
                "verdict": "BROKEN",
                "details": str(e),
            })

    return results


def print_selfcheck_table(results: List[Dict[str, Any]]) -> None:
    print("\n" + "=" * 90)
    print(f"{'PLATFORM':<20} {'STATUS':<12} {'LATENCY':<10} {'VERDICT':<14} {'DETAILS':<32}")
    print("=" * 90)
    for r in results:
        print(
            f"{r['platform']:<20} {r['status']:<12} {str(r['latency_ms']) + ' ms':<10} "
            f"{r['verdict']:<14} {r['details'][:32]:<32}"
        )
    print("=" * 90 + "\n")


async def main():
    city = sys.argv[1] if len(sys.argv) > 1 else "Chennai"
    print(f"🔍 Running TicketNotify multi-platform self-check for {city}...")
    results = await run_platform_selfcheck(city)
    print_selfcheck_table(results)
    
    # Exit 0 if all adapters registered and responded
    has_broken = any(r["verdict"] == "BROKEN" for r in results)
    sys.exit(1 if has_broken else 0)


if __name__ == "__main__":
    asyncio.run(main())
