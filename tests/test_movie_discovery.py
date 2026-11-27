"""Tests for enhanced movie discovery, release dates, and category transitions."""

import pytest
from datetime import date, timedelta
from ticketnotify.engine.discovery import (
    format_theatrical_date,
    format_release_countdown,
    categorize_movie,
    get_movie_catalog_by_category,
    paginate_movies,
    format_movie_card,
    get_current_ist_date,
)


def test_format_theatrical_date():
    assert format_theatrical_date("2026-11-21") == "21 November 2026"
    assert format_theatrical_date("2026-12-18") == "18 December 2026"
    assert format_theatrical_date(None) == "Release date not confirmed"


def test_format_release_countdown():
    today = get_current_ist_date()

    # Past release
    past_date = (today - timedelta(days=5)).strftime("%Y-%m-%d")
    label, delta = format_release_countdown(past_date)
    assert "Running since" in label
    assert delta == -5

    # Today release
    today_date = today.strftime("%Y-%m-%d")
    label, delta = format_release_countdown(today_date)
    assert "TODAY" in label
    assert delta == 0

    # Tomorrow release
    tomorrow_date = (today + timedelta(days=1)).strftime("%Y-%m-%d")
    label, delta = format_release_countdown(tomorrow_date)
    assert "TOMORROW" in label
    assert delta == 1

    # Future release (22 days)
    future_date = (today + timedelta(days=22)).strftime("%Y-%m-%d")
    label, delta = format_release_countdown(future_date)
    assert "22 days remaining" in label
    assert delta == 22


def test_categorize_movie_auto_transition():
    today = get_current_ist_date()

    # Movie released yesterday -> must be now_showing
    yesterday = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    assert categorize_movie({"release_date": yesterday}, today=today) == "now_showing"

    # Movie releasing today -> now_showing
    today_str = today.strftime("%Y-%m-%d")
    assert categorize_movie({"release_date": today_str}, today=today) == "now_showing"

    # Movie releasing next month -> coming_soon
    next_month = (today + timedelta(days=30)).strftime("%Y-%m-%d")
    assert categorize_movie({"release_date": next_month}, today=today) == "coming_soon"


def test_category_filters():
    now_showing = get_movie_catalog_by_category("now_showing")
    coming_soon = get_movie_catalog_by_category("coming_soon")

    assert len(now_showing) > 0
    assert len(coming_soon) > 0

    # Every item in now_showing should have is_now_showing == True
    for m in now_showing:
        assert m["is_now_showing"] is True
        assert "Theatrical Release:" in format_movie_card(m, category="now_showing")

    # Every item in coming_soon should have is_now_showing == False
    for m in coming_soon:
        assert m["is_now_showing"] is False
        assert "Confirmed Release:" in format_movie_card(m, category="coming_soon")


def test_pagination():
    movies = [{"title": f"Movie {i}"} for i in range(10)]
    p0, total_pages, count = paginate_movies(movies, page=0, page_size=3)
    assert len(p0) == 3
    assert total_pages == 4
    assert count == 10
    assert p0[0]["title"] == "Movie 0"


def test_merge_and_dedup_catalogs():
    from ticketnotify.engine.discovery import merge_and_dedup_catalogs

    local = [
        {"title": "Spider-Man: Beyond the Spider-Verse", "release_date": "2027-04-10", "languages": ["English"]},
    ]
    tmdb = [
        # Duplicate with slightly different casing/subtitle
        {"title": "Spider-Man: Beyond the Spider-Verse", "release_date": "2027-04-10", "languages": ["Tamil", "Hindi"]},
        # Brand new movie
        {"title": "Toy Story 5", "release_date": "2026-06-19", "languages": ["English"]},
    ]

    merged = merge_and_dedup_catalogs(local, tmdb)
    assert len(merged) == 2
    spidey = next(m for m in merged if "Spider-Man" in m["title"])
    # Languages merged
    assert "Tamil" in spidey["languages"]
    assert "English" in spidey["languages"]
    toy = next(m for m in merged if "Toy Story" in m["title"])
    assert toy["release_date"] == "2026-06-19"


def test_is_upcoming_movie_check():
    from ticketnotify.engine.discovery import is_upcoming_movie

    today = get_current_ist_date()
    future = (today + timedelta(days=15)).strftime("%Y-%m-%d")
    past = (today - timedelta(days=15)).strftime("%Y-%m-%d")

    catalog = [
        {"title": "Upcoming Blockbuster", "release_date": future},
        {"title": "Old Classic", "release_date": past},
    ]

    assert is_upcoming_movie("Upcoming Blockbuster", catalog=catalog) is True
    assert is_upcoming_movie("Old Classic", catalog=catalog) is False
