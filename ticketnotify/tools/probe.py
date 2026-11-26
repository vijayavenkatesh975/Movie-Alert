"""Live platform adapter probe CLI tool.

Usage:
    python -m ticketnotify.tools.probe <platform> <city> <movie> [--date YYYY-MM-DD]
"""

import asyncio
import sys
import time
import argparse
from datetime import datetime

from ticketnotify.adapters.registry import registry
from ticketnotify.location.geocoder import geocoder
from ticketnotify.location.matcher import map_location_to_platforms
from ticketnotify.location.models import NormalizedLocation


async def probe_platform(platform_name: str, city_name: str, movie_title: str, target_date: str | None = None) -> None:
    print("=" * 70)
    print(f"  🔍 PROBING ADAPTER: [{platform_name.upper()}]")
    print(f"  📍 Location:        {city_name}")
    print(f"  🎬 Movie Query:     '{movie_title}'")
    query_date = target_date or datetime.now().strftime("%Y-%m-%d")
    print(f"  📅 Target Date:     {query_date}")
    print("=" * 70)

    adapter = registry.get_adapter(platform_name)
    if not adapter:
        print(f"❌ Error: Platform '{platform_name}' not found. Available: {list(registry.get_all_adapters().keys())}")
        return

    # Geocode location or construct fallback NormalizedLocation
    print("\n[1/4] Normalizing location...")
    loc = await geocoder.geocode(city_name)
    if not loc:
        loc = NormalizedLocation(
            raw_query=city_name,
            city=city_name.title(),
            country="India",
            country_code="in",
            latitude=12.9716,
            longitude=77.5946,
            display_name=f"{city_name}, India",
        )
    loc = map_location_to_platforms(loc)
    print(f"   • City:        {loc.city} ({loc.country})")
    print(f"   • Coordinates: {loc.latitude}, {loc.longitude}")
    print(f"   • Platform Code ({platform_name}): {loc.platform_codes.get(platform_name, 'N/A')}")

    # Check health
    print("\n[2/4] Testing health check endpoint...")
    t0 = time.perf_counter()
    is_healthy = await adapter.health_check()
    health_latency = (time.perf_counter() - t0) * 1000
    status_icon = "✅ 200 OK" if is_healthy else "⚠️ UNHEALTHY / BLOCKED"
    print(f"   • Health Status: {status_icon} (Latency: {health_latency:.1f}ms)")

    # Search movie
    print(f"\n[3/4] Searching for movie '{movie_title}'...")
    t0 = time.perf_counter()
    matches = await adapter.search_movie(movie_title, loc)
    search_latency = (time.perf_counter() - t0) * 1000
    print(f"   • Found: {len(matches)} match(es) (Latency: {search_latency:.1f}ms)")

    selected_movie_id = None
    if matches:
        for idx, m in enumerate(matches[:3], 1):
            print(f"     [{idx}] ID: {m.movie_id} | Title: {m.title} | Formats: {','.join(m.formats)} | URL: {m.url}")
        selected_movie_id = matches[0].movie_id
    else:
        print(f"   • No direct matches; simulating lookup for query.")
        selected_movie_id = f"PROBE_{movie_title.upper()[:6]}"

    # Fetch cinemas
    print(f"\n[4/4] Fetching cinemas and shows within 15 km...")
    t0 = time.perf_counter()
    cinemas = await adapter.get_cinemas(loc, radius_km=15.0)
    cinema_latency = (time.perf_counter() - t0) * 1000
    print(f"   • Cinemas found: {len(cinemas)} (Latency: {cinema_latency:.1f}ms)")
    for c in cinemas[:3]:
        dist_str = f"{c.distance_km} km" if c.distance_km is not None else "N/A"
        print(f"     • {c.name} ({c.chain or 'Ind'}) - {dist_str}")

    # Fetch shows
    t0 = time.perf_counter()
    res = await adapter.get_shows(selected_movie_id, loc, target_date=query_date)
    show_latency = (time.perf_counter() - t0) * 1000

    if not res.is_success:
        print(f"   • Fetch Status: ⚠️ {res.status.value} (Latency: {show_latency:.1f}ms)")
        print(f"   • Error Detail: {res.error_message}")
    else:
        print(f"   • Fetch Status: ✅ OK - Shows found: {len(res.shows)} (Latency: {show_latency:.1f}ms)")
        if res.shows:
            print("\n--- SAMPLE SHOWS PARSED ---")
            for s in res.shows[:5]:
                print(f"  🎬 [{s.format}] {s.cinema_name} @ {s.time}")
                print(f"     Status: {s.seat_status_display} | Price: {s.price_display} | Lang: {s.language}")
                print(f"     Deep Link: {s.booking_url}")
                print()
        else:
            print("  ℹ️ 0 active shows currently open on this date for this movie.")

    print("=" * 70)
    print("  ✅ Probe complete.")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="Probe TicketNotify cinema platform adapter")
    parser.add_argument("platform", choices=["bms", "ticketnew", "district", "pvrinox"], help="Platform adapter to probe")
    parser.add_argument("city", help="City name e.g. Bengaluru, Chennai, Mumbai")
    parser.add_argument("movie", help="Movie name or keyword e.g. Avatar, Leo, Pushpa")
    parser.add_argument("--date", default=None, help="Show date YYYY-MM-DD")

    args = parser.parse_args()
    asyncio.run(probe_platform(args.platform, args.city, args.movie, args.date))


if __name__ == "__main__":
    main()
