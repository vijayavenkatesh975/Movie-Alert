"""Matcher mapping normalized locations to platform-specific codes."""

from typing import Dict, Optional, Tuple, List
from ticketnotify.location.models import NormalizedLocation

# Operating countries per platform (ISO 2-letter codes)
PLATFORM_OPERATING_COUNTRIES: Dict[str, List[str]] = {
    "bms": ["in", "ae", "id", "lk"],            # India, UAE, Indonesia, Sri Lanka
    "ticketnew": ["in"],                         # India
    "district": ["in", "ae"],                    # India, UAE
    "pvrinox": ["in", "lk"],                     # India, Sri Lanka
    # Templates / Extensible platforms
    "fandango": ["us"],                          # United States
    "amc": ["us"],                               # United States
    "cineworld": ["gb", "ie"],                   # UK, Ireland
    "voxcinemas": ["ae", "sa", "eg", "qa", "kw", "om", "bh"], # Middle East
}

# BookMyShow city code mappings
BMS_CITY_CODES = {
    "bengaluru": "BANG",
    "bangalore": "BANG",
    "mumbai": "MUMBAI",
    "delhi": "NCR",
    "new delhi": "NCR",
    "gurgaon": "NCR",
    "noida": "NCR",
    "chennai": "CHEN",
    "hyderabad": "HYD",
    "kolkata": "KOLK",
    "pune": "PUNE",
    "ahmedabad": "AHMD",
    "chandigarh": "CHD",
    "kochi": "KOCH",
    "coimbatore": "COIM",
    "jaipur": "JAIP",
    "lucknow": "LUCK",
    "nagpur": "NAGP",
    "indore": "INDO",
    "bhopal": "BHOP",
    "vadodara": "VAD",
    "surat": "SURT",
    "visakhapatnam": "VIZ",
    "patna": "PAT",
    "dubai": "DUBAI",
    "abu dhabi": "ABU",
}

# Ticketnew city slugs
TICKETNEW_CITY_CODES = {
    "chennai": "chennai",
    "bengaluru": "bangalore",
    "bangalore": "bangalore",
    "coimbatore": "coimbatore",
    "madurai": "madurai",
    "hyderabad": "hyderabad",
    "mumbai": "mumbai",
    "delhi": "delhi",
    "new delhi": "delhi",
    "trichy": "trichy",
    "salem": "salem",
    "tirunelveli": "tirunelveli",
    "vellore": "vellore",
    "puducherry": "puducherry",
    "pondicherry": "puducherry",
    "kochi": "kochi",
    "calicut": "kozhikode",
    "thiruvananthapuram": "trivandrum",
}

# District (by Zomato) city slugs
DISTRICT_CITY_CODES = {
    "bengaluru": "bengaluru",
    "bangalore": "bengaluru",
    "mumbai": "mumbai",
    "delhi": "delhi-ncr",
    "new delhi": "delhi-ncr",
    "gurgaon": "delhi-ncr",
    "noida": "delhi-ncr",
    "hyderabad": "hyderabad",
    "chennai": "chennai",
    "pune": "pune",
    "kolkata": "kolkata",
    "ahmedabad": "ahmedabad",
    "chandigarh": "chandigarh",
    "jaipur": "jaipur",
    "goa": "goa",
    "dubai": "dubai",
}

# PVR INOX city names
PVRINOX_CITY_CODES = {
    "bengaluru": "Bengaluru",
    "bangalore": "Bengaluru",
    "mumbai": "Mumbai",
    "delhi": "Delhi-NCR",
    "new delhi": "Delhi-NCR",
    "gurgaon": "Delhi-NCR",
    "noida": "Delhi-NCR",
    "chennai": "Chennai",
    "hyderabad": "Hyderabad",
    "kolkata": "Kolkata",
    "pune": "Pune",
    "ahmedabad": "Ahmedabad",
    "kochi": "Kochi",
    "chandigarh": "Chandigarh",
    "jaipur": "Jaipur",
    "lucknow": "Lucknow",
    "indore": "Indore",
    "bhopal": "Bhopal",
    "surat": "Surat",
    "vadodara": "Vadodara",
    "nagpur": "Nagpur",
    "coimbatore": "Coimbatore",
}


def map_location_to_platforms(location: NormalizedLocation) -> NormalizedLocation:
    """Populates platform_codes and supported/unsupported platforms for location."""
    c_code = (location.country_code or "").lower()
    city_norm = (location.city or "").lower().strip()

    platform_codes: Dict[str, Optional[str]] = {}
    supported: List[str] = []
    unsupported: List[str] = []

    # Check BMS
    if c_code in PLATFORM_OPERATING_COUNTRIES["bms"]:
        code = BMS_CITY_CODES.get(city_norm) or city_norm.upper()[:6]
        platform_codes["bms"] = code
        supported.append("bms")
    else:
        unsupported.append("bms")

    # Check Ticketnew
    if c_code in PLATFORM_OPERATING_COUNTRIES["ticketnew"]:
        code = TICKETNEW_CITY_CODES.get(city_norm) or city_norm.replace(" ", "-")
        platform_codes["ticketnew"] = code
        supported.append("ticketnew")
    else:
        unsupported.append("ticketnew")

    # Check District
    if c_code in PLATFORM_OPERATING_COUNTRIES["district"]:
        code = DISTRICT_CITY_CODES.get(city_norm) or city_norm.replace(" ", "-")
        platform_codes["district"] = code
        supported.append("district")
    else:
        unsupported.append("district")

    # Check PVR INOX
    if c_code in PLATFORM_OPERATING_COUNTRIES["pvrinox"]:
        code = PVRINOX_CITY_CODES.get(city_norm) or (location.city.title() if location.city else "Bengaluru")
        platform_codes["pvrinox"] = code
        supported.append("pvrinox")
    else:
        unsupported.append("pvrinox")

    location.platform_codes = platform_codes
    location.supported_platforms = supported
    location.unsupported_platforms = unsupported
    return location
