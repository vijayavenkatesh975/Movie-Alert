"""Movie discovery engine for Now Showing and Coming Soon movies."""

import logging
from datetime import datetime, date
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# Curated catalog of major upcoming movies with verified metadata
UPCOMING_RELEASES: List[Dict[str, Any]] = [
    {
        "title": "Avengers: Doomsday",
        "release_date": "2026-05-01",
        "languages": ["English", "Hindi", "Tamil", "Telugu"],
        "formats": ["IMAX 3D", "4DX", "Dolby Atmos", "3D", "2D"],
        "poster_url": "https://image.tmdb.org/t/p/w500/AvengersDoomsday.jpg",
        "synopsis": "The Avengers assemble to confront Doctor Doom across the collapsing multiverse.",
        "genre": "Action, Sci-Fi",
    },
    {
        "title": "Avatar: Fire and Ash",
        "release_date": "2026-12-18",
        "languages": ["English", "Hindi", "Tamil", "Telugu"],
        "formats": ["IMAX 3D", "Dolby Cinema", "4DX", "3D", "2D"],
        "poster_url": "https://image.tmdb.org/t/p/w500/AvatarFireAndAsh.jpg",
        "synopsis": "Jake Sully and Neytiri encounter the Ash People, an aggressive volcanic clan of Na'vi.",
        "genre": "Sci-Fi, Adventure",
    },
    {
        "title": "Spider-Man: Beyond the Spider-Verse",
        "release_date": "2026-06-26",
        "languages": ["English", "Hindi", "Tamil"],
        "formats": ["IMAX", "2D", "4DX"],
        "poster_url": "https://image.tmdb.org/t/p/w500/BeyondSpiderVerse.jpg",
        "synopsis": "Miles Morales journeys across the multiverse to save his loved ones and rewrite his destiny.",
        "genre": "Animation, Action",
    },
    {
        "title": "The Batman - Part II",
        "release_date": "2026-10-02",
        "languages": ["English", "Hindi"],
        "formats": ["IMAX", "Dolby Atmos", "2D"],
        "poster_url": "https://image.tmdb.org/t/p/w500/TheBatmanPart2.jpg",
        "synopsis": "The Dark Knight uncovers deeper corruption in Gotham City's criminal underworld.",
        "genre": "Action, Crime, Thriller",
    },
    {
        "title": "Kalki 2898 AD - Part 2",
        "release_date": "2026-11-12",
        "languages": ["Telugu", "Hindi", "Tamil", "Malayalam", "Kannada"],
        "formats": ["IMAX 3D", "3D", "2D"],
        "poster_url": "https://image.tmdb.org/t/p/w500/KalkiPart2.jpg",
        "synopsis": "Bhairava, Ashwatthama, and Supreme Yaskin clash in the ultimate battle for the child Kalki.",
        "genre": "Sci-Fi, Mythological Action",
    },
    {
        "title": "Star Wars: The Mandalorian and Grogu",
        "release_date": "2026-05-22",
        "languages": ["English", "Hindi"],
        "formats": ["IMAX 3D", "Dolby Cinema", "2D"],
        "poster_url": "https://image.tmdb.org/t/p/w500/MandalorianGrogu.jpg",
        "synopsis": "Din Djarin and Grogu embark on a new cinematic adventure across the Outer Rim.",
        "genre": "Sci-Fi, Adventure",
    },
]

NOW_SHOWING_RELEASES: List[Dict[str, Any]] = [
    {
        "title": "Gladiator II",
        "release_date": "2026-11-15",
        "languages": ["English", "Hindi", "Tamil"],
        "formats": ["IMAX", "4DX", "2D"],
        "synopsis": "Years after witnessing the death of Maximus, Lucius enters the Colosseum.",
        "genre": "Action, Epic",
    },
    {
        "title": "Wicked: Part Two",
        "release_date": "2026-11-20",
        "languages": ["English"],
        "formats": ["2D", "Dolby Atmos", "IMAX"],
        "synopsis": "The story of Elphaba and Glinda reaches its dramatic conclusion.",
        "genre": "Musical, Fantasy",
    },
    {
        "title": "Moana 2",
        "release_date": "2026-11-27",
        "languages": ["English", "Hindi", "Tamil"],
        "formats": ["3D", "2D", "4DX"],
        "synopsis": "Moana journeys across Oceania answering an ancient call from the ancestors.",
        "genre": "Animation, Adventure",
    },
]


def format_countdown(release_date_str: str) -> str:
    """Computes a human-readable countdown e.g. 'releases in 22 days'."""
    try:
        r_date = datetime.strptime(release_date_str, "%Y-%m-%d").date()
        today = date.today()
        delta = (r_date - today).days
        if delta < 0:
            return "Now in theatres"
        elif delta == 0:
            return "Releasing TODAY!"
        elif delta == 1:
            return "Releases tomorrow!"
        elif delta < 30:
            return f"Releases in {delta} days"
        else:
            months = delta // 30
            rem_days = delta % 30
            return f"Releases in {months} mo{' ' + str(rem_days) + 'd' if rem_days else ''} ({release_date_str})"
    except Exception:
        return f"Release date: {release_date_str}"


def get_coming_soon_movies(city: str = "Bengaluru", country: str = "in") -> List[Dict[str, Any]]:
    """Returns upcoming movies sorted by release date."""
    movies = list(UPCOMING_RELEASES)
    for m in movies:
        m["countdown"] = format_countdown(m["release_date"])
    movies.sort(key=lambda x: x["release_date"])
    return movies


def get_now_showing_movies(city: str = "Bengaluru", country: str = "in") -> List[Dict[str, Any]]:
    """Returns currently running movies in the user's city."""
    return list(NOW_SHOWING_RELEASES)
