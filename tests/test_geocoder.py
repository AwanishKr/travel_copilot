"""
tests/test_geocoder.py
-----------------------
Tests the geocoder's ability to resolve city names to (lat, lon).
No API key or Ollama needed — purely tests the static dict + partial match.

Run: python3 tests/test_geocoder.py
"""

import asyncio
from helpers import header, ok, err, dim

# (city_name, expected_lat_range, expected_lon_range)
EXACT_LOOKUPS = [
    ("delhi",      (28.5, 28.7), (77.1, 77.3)),
    ("manali",     (32.1, 32.4), (77.0, 77.3)),
    ("mumbai",     (18.9, 19.2), (72.7, 72.9)),
    ("chandigarh", (30.6, 30.9), (76.6, 76.9)),
    ("jaipur",     (26.7, 27.1), (75.6, 76.0)),
    ("new delhi",  (28.5, 28.7), (77.1, 77.3)),
]

ALIAS_LOOKUPS = [
    ("bombay",    (18.9, 19.2), (72.7, 72.9)),   # → mumbai
    ("bengaluru", (12.8, 13.1), (77.4, 77.7)),   # → bangalore
    ("mysore",    (12.1, 12.5), (76.5, 76.8)),
]

# Cities that must exist in the Delhi → Manali corridor
CORRIDOR_CITIES = [
    "murthal", "panipat", "ambala", "chandigarh",
    "bilaspur", "mandi", "kullu", "manali",
]

EXTRACT_CASES = [
    ("I want to drive from Delhi to Manali via Chandigarh",
     ["delhi", "manali", "chandigarh"]),
    ("Mumbai to Pune road trip",
     ["mumbai", "pune"]),
    ("How far is Agra from Delhi?",
     ["agra", "delhi"]),
]


def run():
    from tools.geocoder import geocode_sync, extract_cities, CITY_COORDS

    # --- Exact lookups ---
    header("geocoder — exact city lookups")
    for city, lat_range, lon_range in EXACT_LOOKUPS:
        coords = geocode_sync(city)
        if not coords:
            err(f"'{city}' → not found")
            continue
        lat, lon = coords
        if lat_range[0] <= lat <= lat_range[1] and lon_range[0] <= lon <= lon_range[1]:
            ok(f"'{city}' → ({lat}, {lon})")
        else:
            err(f"'{city}' → ({lat}, {lon}) — outside expected range {lat_range}, {lon_range}")

    # --- Alias / partial match ---
    header("geocoder — aliases and partial matches")
    for city, lat_range, lon_range in ALIAS_LOOKUPS:
        coords = geocode_sync(city)
        if not coords:
            err(f"'{city}' → not found")
            continue
        lat, lon = coords
        if lat_range[0] <= lat <= lat_range[1] and lon_range[0] <= lon <= lon_range[1]:
            ok(f"'{city}' → ({lat}, {lon})")
        else:
            err(f"'{city}' → ({lat}, {lon}) — outside expected range")

    # --- Delhi → Manali corridor ---
    header("geocoder — Delhi → Manali corridor coverage")
    missing = [c for c in CORRIDOR_CITIES if geocode_sync(c) is None]
    if missing:
        err(f"Missing from static dict: {missing}")
    else:
        ok(f"All {len(CORRIDOR_CITIES)} corridor cities present")

    # --- Total dict size ---
    header("geocoder — static dict stats")
    ok(f"Total cities in static dict: {len(CITY_COORDS)}")

    # --- extract_cities ---
    header("geocoder — extract_cities()")
    for text, expected in EXTRACT_CASES:
        found = extract_cities(text)
        matched = all(c in found for c in expected)
        if matched:
            ok(f'"{text[:50]}..."')
            dim(f"     found: {found}")
        else:
            err(f'"{text[:50]}..."')
            dim(f"     expected subset: {expected}")
            dim(f"     got: {found}")


if __name__ == "__main__":
    run()
