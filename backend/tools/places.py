"""
tools/places.py
---------------
POI search using Google Places API.

place_type values accepted:
    "restaurant"  — dhabas and restaurants
    "gas_station" — fuel stops
    "lodging"     — hotels
    "hospital"    — emergency
    "atm"         — cash
"""

import httpx
from config import GOOGLE_PLACES_KEY

_BASE    = "https://maps.googleapis.com/maps/api/place"
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)

_KEYWORDS = {
    "restaurant": "dhaba",
    "gas_station": "petrol pump",
    "lodging":     "hotel",
    "hospital":    "hospital",
    "atm":         "ATM",
}


async def search_nearby(
    coords: tuple[float, float],
    place_type: str = "restaurant",
    radius_m: int = 5000,
) -> list[dict]:
    """
    Search for places near a coordinate point using Google Places API.

    Returns list of:
    {
        "name":          "Haveli Dhaba",
        "address":       "NH-44, Murthal",
        "rating":        4.3,
        "total_ratings": 1200,
        "open_now":      True,
        "coords":        (29.09, 77.01),
        "place_id":      "ChIJ...",
    }
    """
    if not GOOGLE_PLACES_KEY:
        return []

    lat, lon = coords
    params = {
        "location": f"{lat},{lon}",
        "radius":   radius_m,
        "type":     place_type,
        "keyword":  _KEYWORDS.get(place_type, ""),
        "key":      GOOGLE_PLACES_KEY,
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(f"{_BASE}/nearbysearch/json", params=params)
            resp.raise_for_status()
            data = resp.json()

        results = []
        for place in data.get("results", [])[:5]:
            loc = place.get("geometry", {}).get("location", {})
            oh  = place.get("opening_hours", {})
            results.append({
                "name":          place.get("name", "Unknown"),
                "address":       place.get("vicinity", ""),
                "rating":        place.get("rating"),
                "total_ratings": place.get("user_ratings_total", 0),
                "open_now":      oh.get("open_now"),
                "coords":        (loc.get("lat"), loc.get("lng")),
                "place_id":      place.get("place_id", ""),
            })

        return results

    except Exception as e:
        print(f"[places] Search failed near {coords}: {e}")
        return []


async def search_along_route(
    geometry_coords: list[tuple[float, float]],
    place_type: str = "restaurant",
    sample_every_n: int = 2,
) -> list[dict]:
    """
    Search for places along a route by sampling geometry points.

    geometry_coords comes from trip_context["geometry"] — already sampled
    every 40km. sample_every_n=2 searches every ~80km.

    Deduplicates by place_id, returns combined list.
    """
    import asyncio

    sample_points = geometry_coords[::sample_every_n]
    results_per_point = await asyncio.gather(*[
        search_nearby(pt, place_type=place_type)
        for pt in sample_points
    ])

    seen = set()
    combined = []
    for places in results_per_point:
        for p in places:
            pid = p.get("place_id") or p["name"]
            if pid not in seen:
                seen.add(pid)
                combined.append(p)

    return combined
