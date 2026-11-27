"""Tests for city-wide manual theatre selection, filters, search, and persistence."""

import pytest
import time
from ticketnotify.location.models import NormalizedLocation
from ticketnotify.location.theatre_merger import (
    get_theatres_for_location,
    filter_and_sort_theatres,
    get_unique_localities,
    get_unique_chains,
    MergedCinema,
)
from ticketnotify.database.models import User, Alert, Location
from ticketnotify.database.session import get_db_session, init_db
from ticketnotify.database.crud import (
    get_or_create_user,
    update_user_selected_theatres,
    update_alert_cinemas,
)


@pytest.mark.asyncio
async def test_city_wide_theatres_no_radius_cutoff():
    """Verify Chennai retrieves all city-wide theatres without radius restriction."""
    chennai_loc = NormalizedLocation(
        raw_query="Chennai",
        city="Chennai",
        country="India",
        country_code="in",
        latitude=13.0827,
        longitude=80.2707,
        display_name="Chennai, India",
    )

    theatres = await get_theatres_for_location(chennai_loc, radius_km=None)
    assert len(theatres) >= 20  # Comprehensive city coverage

    # Verify iconic Chennai cinemas exist
    names = [t.name for t in theatres]
    assert any("Palazzo" in n for n in names)
    assert any("Luxe" in n for n in names)
    assert any("Sathyam" in n for n in names)
    assert any("AGS" in n for n in names)
    assert any("Rohini" in n for n in names)

    # Verify platform-specific IDs are preserved
    palazzo = next(t for t in theatres if "Palazzo" in t.name)
    assert "bms" in palazzo.platform_cinema_ids
    assert "pvrinox" in palazzo.platform_cinema_ids
    assert palazzo.canonical_id.startswith("cin_")


def test_theatre_filtering_and_search():
    theatres = [
        MergedCinema(
            canonical_id="c1",
            name="PVR Palazzo – Vadapalani",
            city="Chennai",
            chain="PVR",
            locality="Vadapalani",
            mall="Nexus Vijaya Mall",
            distance_km=2.5,
        ),
        MergedCinema(
            canonical_id="c2",
            name="INOX Luxe – Velachery",
            city="Chennai",
            chain="INOX",
            locality="Velachery",
            mall="Phoenix Marketcity",
            distance_km=8.1,
        ),
        MergedCinema(
            canonical_id="c3",
            name="AGS Cinemas – T. Nagar",
            city="Chennai",
            chain="AGS",
            locality="T. Nagar",
            mall=None,
            distance_km=4.0,
        ),
        MergedCinema(
            canonical_id="c4",
            name="Rohini Silver Screens – Koyambedu",
            city="Chennai",
            chain="Rohini",
            locality="Koyambedu",
            mall=None,
            distance_km=6.3,
        ),
    ]

    # Locality filter
    vadapalani = filter_and_sort_theatres(theatres, locality="Vadapalani")
    assert len(vadapalani) == 1
    assert vadapalani[0].name == "PVR Palazzo – Vadapalani"

    # Chain filter
    inox = filter_and_sort_theatres(theatres, chain="INOX")
    assert len(inox) == 1
    assert inox[0].name == "INOX Luxe – Velachery"

    # Search by Mall name
    phoenix = filter_and_sort_theatres(theatres, query="Phoenix")
    assert len(phoenix) == 1
    assert phoenix[0].name == "INOX Luxe – Velachery"

    # Search by Cinema name
    rohini = filter_and_sort_theatres(theatres, query="Rohini")
    assert len(rohini) == 1
    assert rohini[0].name == "Rohini Silver Screens – Koyambedu"

    # Distance sort vs Alphabetical sort
    dist_sorted = filter_and_sort_theatres(theatres, sort_by="distance")
    assert dist_sorted[0].name == "PVR Palazzo – Vadapalani"  # 2.5 km
    assert dist_sorted[-1].name == "INOX Luxe – Velachery"    # 8.1 km

    alpha_sorted = filter_and_sort_theatres(theatres, sort_by="alpha")
    assert alpha_sorted[0].name == "AGS Cinemas – T. Nagar"
    assert alpha_sorted[-1].name == "Rohini Silver Screens – Koyambedu"


@pytest.mark.asyncio
async def test_theatre_selection_persistence_and_per_movie():
    """Tests persisting default user theatres and customizing per movie alert."""
    await init_db()
    unique_tg = int(time.time() * 1000) % 1000000000

    async with get_db_session() as session:
        user, _ = await get_or_create_user(session, telegram_id=unique_tg, username=f"user_{unique_tg}")
        
        # 1. Persist user default city-wide theatre preferences
        save_dict = {
            "city": "Chennai",
            "canonical_ids": ["cin_palazzo_01", "cin_luxe_02"],
            "names": ["PVR Palazzo", "INOX Luxe"],
            "platform_cinema_ids": {"bms": ["PVPL_CHE", "INLX_CHE"]},
        }
        await update_user_selected_theatres(session, user.id, save_dict, chains=["PVR", "INOX"])

        # Create alert with custom per-movie theatres (e.g. Rohini + AGS for Jailer 2)
        loc = Location(
            user_id=user.id,
            name="Chennai",
            normalized_city="Chennai",
            normalized_country="India",
            country_code="in",
            latitude=13.0827,
            longitude=80.2707,
        )
        session.add(loc)
        await session.flush()

        alert = Alert(
            user_id=user.id,
            location_id=loc.id,
            movie_query="Jailer 2",
            platforms=["bms"],
            alert_types=["bookings_opened"],
            selected_cinemas={
                "canonical_ids": ["cin_rohini_03", "cin_ags_04"],
                "names": ["Rohini Silver Screens", "AGS Cinemas T. Nagar"],
            },
        )
        session.add(alert)
        await session.commit()

    # 2. Read back from database and verify persistence across fresh session
    async with get_db_session() as session:
        user_read, _ = await get_or_create_user(session, telegram_id=unique_tg)
        assert user_read.selected_theatres["city"] == "Chennai"
        assert "cin_palazzo_01" in user_read.selected_theatres["canonical_ids"]
        assert "cin_luxe_02" in user_read.selected_theatres["canonical_ids"]
        assert "PVR" in user_read.selected_chains

        # Verify alert retained its own custom theatre list
        from ticketnotify.database.crud import get_user_alerts
        user_alerts = await get_user_alerts(session, user_read.id)
        assert len(user_alerts) == 1
        jailer_alert = user_alerts[0]
        assert jailer_alert.movie_query == "Jailer 2"
        assert "cin_rohini_03" in jailer_alert.selected_cinemas["canonical_ids"]
        assert "Rohini Silver Screens" in jailer_alert.selected_cinemas["names"]
