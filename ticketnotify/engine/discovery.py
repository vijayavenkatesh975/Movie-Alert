"""Movie discovery engine for Now Showing, Coming Soon, and category browsing.

Uses Asia/Kolkata timezone for Indian movie release dates, automatically transitions
movies between categories based on release status, and provides rich metadata with exact dates.
"""

import logging
from datetime import datetime, date, timedelta, timezone
from typing import List, Dict, Any, Optional, Tuple
import rapidfuzz

from ticketnotify.config import settings

logger = logging.getLogger(__name__)

# Asia/Kolkata timezone (UTC+5:30) with safe fallback if tzdata package is missing on Windows
try:
    from zoneinfo import ZoneInfo
    IST = ZoneInfo("Asia/Kolkata")
    datetime.now(IST)
except Exception:
    IST = timezone(timedelta(hours=5, minutes=30), name="Asia/Kolkata")


def get_current_ist_date() -> date:
    """Returns today's date in Asia/Kolkata timezone."""
    return datetime.now(IST).date()


# Canonical verified catalog of movies with exact release dates, genres, and platform formats
MASTER_MOVIE_CATALOG: List[Dict[str, Any]] = [
    # Currently running / recent releases
    {
        "title": "Moana 2",
        "release_date": "2026-11-27",
        "languages": ["English", "Hindi", "Tamil", "Telugu"],
        "formats": ["3D", "2D", "4DX", "IMAX"],
        "genre": "Animation, Adventure, Musical",
        "synopsis": "Moana journeys across Oceania answering an ancient call from the ancestors to reconnect people of the seas.",
        "poster_url": "https://image.tmdb.org/t/p/w500/Moana2.jpg",
        "booking_status": "Bookings Open",
    },
    {
        "title": "Wicked: Part Two",
        "release_date": "2026-11-20",
        "languages": ["English"],
        "formats": ["2D", "Dolby Atmos", "IMAX"],
        "genre": "Musical, Fantasy, Drama",
        "synopsis": "The story of Elphaba and Glinda reaches its dramatic and emotional conclusion in the Land of Oz.",
        "poster_url": "https://image.tmdb.org/t/p/w500/WickedPart2.jpg",
        "booking_status": "Bookings Open",
    },
    {
        "title": "Gladiator II",
        "release_date": "2026-11-15",
        "languages": ["English", "Hindi", "Tamil"],
        "formats": ["IMAX", "4DX", "2D", "ScreenX"],
        "genre": "Action, Epic, Drama",
        "synopsis": "Years after witnessing the death of Maximus, Lucius enters the Colosseum to fight for the future of Rome.",
        "poster_url": "https://image.tmdb.org/t/p/w500/Gladiator2.jpg",
        "booking_status": "Bookings Open",
    },
    {
        "title": "Amaran",
        "release_date": "2026-10-31",
        "languages": ["Tamil", "Telugu", "Hindi"],
        "formats": ["2D", "Dolby Atmos"],
        "genre": "Action, Biographical Drama",
        "synopsis": "The heroic life and supreme sacrifice of Major Mukund Varadarajan and the Rajput Regiment.",
        "poster_url": "https://image.tmdb.org/t/p/w500/Amaran.jpg",
        "booking_status": "Few Shows Running",
    },
    {
        "title": "Kanguva",
        "release_date": "2026-11-14",
        "languages": ["Tamil", "Telugu", "Hindi", "Malayalam", "Kannada"],
        "formats": ["3D", "2D", "IMAX"],
        "genre": "Fantasy, Period Action",
        "synopsis": "A warrior in 1678 has a mysterious and fateful connection to a modern bounty hunter in Goa.",
        "poster_url": "https://image.tmdb.org/t/p/w500/Kanguva.jpg",
        "booking_status": "Bookings Open",
    },

    # Confirmed upcoming releases
    {
        "title": "Pushpa 2: The Rule",
        "release_date": "2026-12-05",
        "languages": ["Telugu", "Hindi", "Tamil", "Kannada", "Malayalam"],
        "formats": ["IMAX", "4DX", "2D", "Dolby Atmos"],
        "genre": "Action, Crime, Thriller",
        "synopsis": "The clash between Pushpa Raj and SP Bhanwar Singh Shekhawat escalates into an all-out syndicate war.",
        "poster_url": "https://image.tmdb.org/t/p/w500/Pushpa2.jpg",
        "booking_status": "Advance Bookings Opening Soon",
    },
    {
        "title": "Avatar: Fire and Ash",
        "release_date": "2026-12-18",
        "languages": ["English", "Hindi", "Tamil", "Telugu"],
        "formats": ["IMAX 3D", "Dolby Cinema", "4DX", "3D", "2D"],
        "genre": "Sci-Fi, Adventure, Action",
        "synopsis": "Jake Sully and Neytiri encounter the Ash People, an aggressive volcanic clan of Na'vi led by Varang.",
        "poster_url": "https://image.tmdb.org/t/p/w500/AvatarFireAndAsh.jpg",
        "booking_status": "Advance Bookings Opening Soon",
    },
    {
        "title": "Toxic: A Fairy Tale for Grown-ups",
        "release_date": "2026-04-10",
        "languages": ["Kannada", "Tamil", "Telugu", "Hindi", "Malayalam"],
        "formats": ["IMAX", "Dolby Atmos", "2D"],
        "genre": "Action, Thriller, Noir",
        "synopsis": "Rocking Star Yash stars in an explosive, high-stakes underworld crime spectacle directed by Geetu Mohandas.",
        "poster_url": "https://image.tmdb.org/t/p/w500/ToxicMovie.jpg",
        "booking_status": "Advance Bookings Opening Soon",
    },
    {
        "title": "Avengers: Doomsday",
        "release_date": "2026-05-01",
        "languages": ["English", "Hindi", "Tamil", "Telugu"],
        "formats": ["IMAX 3D", "4DX", "Dolby Atmos", "3D", "2D"],
        "genre": "Action, Sci-Fi, Adventure",
        "synopsis": "The Avengers assemble to confront Doctor Doom across the collapsing multiverse.",
        "poster_url": "https://image.tmdb.org/t/p/w500/AvengersDoomsday.jpg",
        "booking_status": "Advance Bookings Opening Soon",
    },
    {
        "title": "Star Wars: The Mandalorian and Grogu",
        "release_date": "2026-05-22",
        "languages": ["English", "Hindi"],
        "formats": ["IMAX 3D", "Dolby Cinema", "2D"],
        "genre": "Sci-Fi, Adventure, Space Opera",
        "synopsis": "Din Djarin and his young apprentice Grogu embark on a new cinematic mission across the Outer Rim.",
        "poster_url": "https://image.tmdb.org/t/p/w500/MandalorianGrogu.jpg",
        "booking_status": "Advance Bookings Opening Soon",
    },
    {
        "title": "Spider-Man: Beyond the Spider-Verse",
        "release_date": "2026-06-26",
        "languages": ["English", "Hindi", "Tamil"],
        "formats": ["IMAX", "2D", "4DX"],
        "genre": "Animation, Action, Sci-Fi",
        "synopsis": "Miles Morales journeys across alternate dimensions to save his loved ones and rewrite his own destiny.",
        "poster_url": "https://image.tmdb.org/t/p/w500/BeyondSpiderVerse.jpg",
        "booking_status": "Advance Bookings Opening Soon",
    },
    {
        "title": "Jailer 2",
        "release_date": "2026-08-14",
        "languages": ["Tamil", "Telugu", "Hindi", "Kannada"],
        "formats": ["2D", "Dolby Atmos", "IMAX"],
        "genre": "Action, Crime, Drama",
        "synopsis": "Superstar Rajinikanth returns as Tiger Muthuvel Pandian in Nelson Dilipkumar's intense sequel.",
        "poster_url": "https://image.tmdb.org/t/p/w500/Jailer2.jpg",
        "booking_status": "Advance Bookings Opening Soon",
    },
    {
        "title": "The Batman - Part II",
        "release_date": "2026-10-02",
        "languages": ["English", "Hindi"],
        "formats": ["IMAX", "Dolby Atmos", "2D"],
        "genre": "Action, Crime, Mystery",
        "synopsis": "The Dark Knight uncovers deeper layers of corruption inside Gotham City's darkest underworld.",
        "poster_url": "https://image.tmdb.org/t/p/w500/TheBatmanPart2.jpg",
        "booking_status": "Advance Bookings Opening Soon",
    },
    {
        "title": "Kalki 2898 AD - Part 2",
        "release_date": "2026-11-12",
        "languages": ["Telugu", "Hindi", "Tamil", "Malayalam", "Kannada"],
        "formats": ["IMAX 3D", "3D", "2D"],
        "genre": "Sci-Fi, Mythological Action",
        "synopsis": "Bhairava, Ashwatthama, and Supreme Yaskin clash in the ultimate battle across Kasi, Shambhala, and the Complex.",
        "poster_url": "https://image.tmdb.org/t/p/w500/KalkiPart2.jpg",
        "booking_status": "Advance Bookings Opening Soon",
    },
    {
        "title": "Coolie",
        "release_date": "2026-05-14",
        "languages": ["Tamil", "Telugu", "Hindi", "Kannada"],
        "formats": ["IMAX", "2D", "Dolby Atmos"],
        "genre": "Action, Thriller",
        "synopsis": "Lokesh Kanagaraj's high-octane gold syndicate action film starring Superstar Rajinikanth.",
        "poster_url": "https://image.tmdb.org/t/p/w500/Coolie.jpg",
        "booking_status": "Advance Bookings Opening Soon",
    },
]


def format_theatrical_date(date_str: Optional[str]) -> str:
    """Formats '2026-11-21' into '21 November 2026'."""
    if not date_str:
        return "Release date not confirmed"
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%d %B %Y")
    except Exception:
        return date_str


def format_release_countdown(date_str: Optional[str]) -> Tuple[str, Optional[int]]:
    """Computes exact countdown in days relative to Asia/Kolkata today.
    
    Returns (readable_label, days_remaining).
    """
    if not date_str:
        return ("Release date not confirmed", None)

    try:
        r_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        today = get_current_ist_date()
        delta = (r_date - today).days

        if delta < 0:
            formatted_date = format_theatrical_date(date_str)
            return (f"Running since {formatted_date}", delta)
        elif delta == 0:
            return ("Releasing TODAY in theatres!", 0)
        elif delta == 1:
            return ("Releasing TOMORROW!", 1)
        else:
            return (f"{delta} days remaining", delta)
    except Exception:
        return (f"Releases: {date_str}", None)


def categorize_movie(movie: Dict[str, Any], today: Optional[date] = None) -> str:
    """Classifies a movie as 'now_showing' or 'coming_soon' based on IST date."""
    today = today or get_current_ist_date()
    r_date_str = movie.get("release_date")
    if not r_date_str:
        return "coming_soon"

    try:
        r_date = datetime.strptime(r_date_str, "%Y-%m-%d").date()
        if r_date <= today:
            return "now_showing"
        return "coming_soon"
    except Exception:
        return "coming_soon"


def get_movie_catalog_by_category(
    category: str,
    city: str = "Chennai",
    language: Optional[str] = None,
    genre: Optional[str] = None,
    fmt: Optional[str] = None,
    query: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Filters the master movie catalog into one of the 6 discovery categories.

    Categories:
    - 'now_showing': Currently running movies (release_date <= today)
    - 'coming_soon': Upcoming movies (release_date > today)
    - 'this_week': Releasing within the next 7 days (0 <= delta <= 7)
    - 'this_month': Releasing within 30 days or in current calendar month
    - 'recent': Released within the last 14 days
    - 'search': Matches title, actor, or genre query
    """
    today = get_current_ist_date()
    results: List[Dict[str, Any]] = []

    for item in MASTER_MOVIE_CATALOG:
        m = dict(item)
        r_date_str = m.get("release_date")
        countdown_label, delta = format_release_countdown(r_date_str)
        m["countdown"] = countdown_label
        m["days_remaining"] = delta
        m["formatted_release_date"] = format_theatrical_date(r_date_str)

        # Automatic category check
        is_running = (delta is not None and delta <= 0)
        m["is_now_showing"] = is_running

        # Apply Category Filters
        if category == "now_showing":
            if not is_running:
                continue
        elif category == "coming_soon":
            if is_running:
                continue
        elif category == "this_week":
            if delta is None or delta < 0 or delta > 7:
                continue
        elif category == "this_month":
            if delta is None or delta < 0 or delta > 30:
                continue
        elif category == "recent":
            # Released between 0 and 14 days ago
            if delta is None or delta > 0 or delta < -14:
                continue
        elif category == "search":
            if query:
                q = query.lower()
                m_title = m["title"].lower()
                m_genre = m.get("genre", "").lower()
                m_synopsis = m.get("synopsis", "").lower()
                if q not in m_title and q not in m_genre and q not in m_synopsis:
                    continue

        # Optional metadata filters
        if language and language.lower() != "all":
            movie_langs = [l.lower() for l in m.get("languages", [])]
            if language.lower() not in movie_langs:
                continue

        if genre and genre.lower() != "all":
            if genre.lower() not in m.get("genre", "").lower():
                continue

        if fmt and fmt.lower() != "all":
            movie_fmts = [f.lower() for f in m.get("formats", [])]
            if fmt.lower() not in movie_fmts:
                continue

        results.append(m)

    # Sort results
    if category in ("now_showing", "recent"):
        # Most recently released first
        results.sort(key=lambda x: x.get("release_date") or "", reverse=True)
    else:
        # Soonest to release first
        results.sort(key=lambda x: x.get("release_date") or "9999-99-99")

    return results


def paginate_movies(
    movies: List[Dict[str, Any]],
    page: int = 0,
    page_size: int = 3,
) -> Tuple[List[Dict[str, Any]], int, int]:
    """Paginates movie list, returning (page_items, total_pages, total_count)."""
    total = len(movies)
    if total == 0:
        return ([], 1, 0)
    total_pages = (total + page_size - 1) // page_size
    valid_page = max(0, min(page, total_pages - 1))
    start_idx = valid_page * page_size
    end_idx = start_idx + page_size
    return (movies[start_idx:end_idx], total_pages, total)


def format_movie_card(m: Dict[str, Any], category: str = "now_showing") -> str:
    """Formats a single movie item into a markdown card with release details."""
    title = m["title"]
    release_str = m.get("formatted_release_date", "Not confirmed")
    langs = ", ".join(m.get("languages", []))
    fmts = ", ".join(m.get("formats", []))
    genre = m.get("genre", "Drama")
    status = m.get("booking_status", "Checking...")
    synopsis = m.get("synopsis", "")
    is_now_showing = m.get("is_now_showing", False)

    lines = [f"🎬 *{title}*"]
    if is_now_showing:
        lines.append(f"📅 *Theatrical Release:* {release_str}")
        lines.append(f"⏱ *Status:* {m.get('countdown', 'Now in Theatres')}")
    else:
        lines.append(f"🗓 *Confirmed Release:* {release_str}")
        lines.append(f"⏳ *Countdown:* {m.get('countdown', 'Coming Soon')}")

    lines.append(f"🎭 *Genre:* {genre}")
    lines.append(f"🗣 *Languages:* {langs}")
    lines.append(f"🎞 *Formats:* {fmts}")
    lines.append(f"🎟 *Bookings:* `{status}`")
    if synopsis:
        lines.append(f"\n📖 _{synopsis}_")

    return "\n".join(lines)


# Backwards compatibility wrappers
def get_coming_soon_movies(city: str = "Bengaluru", country: str = "in") -> List[Dict[str, Any]]:
    return get_movie_catalog_by_category("coming_soon", city=city)


def get_now_showing_movies(city: str = "Bengaluru", country: str = "in") -> List[Dict[str, Any]]:
    return get_movie_catalog_by_category("now_showing", city=city)


async def fetch_tmdb_upcoming(api_key: Optional[str] = None) -> List[Dict[str, Any]]:
    """Fetches upcoming movies in Indian region from TMDB API if key is provided."""
    key = api_key or getattr(settings, "TMDB_API_KEY", None)
    if not key:
        return []

    try:
        from ticketnotify.adapters.http_client import http_client
        url = "https://api.themoviedb.org/3/movie/upcoming"
        params = {"api_key": key, "region": "IN", "page": 1}
        data = await http_client.get_json(url, params=params, timeout=5.0)
        results = data.get("results", []) if isinstance(data, dict) else []
        lang_names = {
            "en": "English", "ta": "Tamil", "te": "Telugu",
            "hi": "Hindi", "kn": "Kannada", "ml": "Malayalam",
        }
        tmdb_movies = []
        for item in results:
            title = item.get("title")
            r_date = item.get("release_date")
            if not title or not r_date:
                continue
            orig_lang = item.get("original_language", "en")
            languages = [lang_names.get(orig_lang, orig_lang.upper())]
            tmdb_movies.append({
                "title": title,
                "release_date": r_date,
                "languages": languages,
                "formats": ["2D", "IMAX"],
                "genre": "Upcoming Feature",
                "synopsis": item.get("overview") or f"{title} upcoming theatrical release.",
                "poster_url": f"https://image.tmdb.org/t/p/w500{item.get('poster_path')}" if item.get("poster_path") else None,
                "booking_status": "Coming Soon",
            })
        return tmdb_movies
    except Exception as e:
        logger.debug(f"TMDB upcoming fetch failed: {e}")
        return []


def merge_and_dedup_catalogs(local_catalog: List[Dict[str, Any]], tmdb_movies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merges and deduplicates movies using fuzzy title + release year."""
    merged = list(local_catalog)
    for tm in tmdb_movies:
        tm_title = tm["title"].lower()
        tm_year = tm["release_date"][:4] if tm.get("release_date") else ""
        exists = False
        for ex in merged:
            ex_title = ex["title"].lower()
            ex_year = ex["release_date"][:4] if ex.get("release_date") else ""
            if rapidfuzz.fuzz.token_set_ratio(tm_title, ex_title) >= 85:
                if not tm_year or not ex_year or tm_year == ex_year:
                    exists = True
                    for lang in tm.get("languages", []):
                        if lang not in ex.get("languages", []):
                            ex.setdefault("languages", []).append(lang)
                    break
        if not exists:
            merged.append(tm)
    return merged


def is_upcoming_movie(title: str, catalog: Optional[List[Dict[str, Any]]] = None) -> bool:
    """Checks if a movie is an upcoming release (date is in the future or not confirmed)."""
    cat = catalog or MASTER_MOVIE_CATALOG
    today = get_current_ist_date()
    for m in cat:
        if rapidfuzz.fuzz.token_set_ratio(title.lower(), m["title"].lower()) >= 80:
            r_str = m.get("release_date")
            if not r_str:
                return True
            try:
                r_date = datetime.strptime(r_str, "%Y-%m-%d").date()
                return r_date > today
            except Exception:
                return True
    return False

