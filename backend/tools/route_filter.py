"""
tools/route_filter.py
---------------------
Deterministic filter: raw Mappls route JSON → travel_context.

Extracts only what the route agent needs:
  - major_corridors  : named highway / expressway segments with km extents
  - major_cities     : known cities along the route with km marks

Everything else (rest stops, dhabas, terrain transitions) is left to
downstream specialist agents that can search the web at query time.
"""

import re
import reverse_geocoder as rg
from tools.polyline import decode, sample, haversine_km

# ── Road classification ───────────────────────────────────────────────────────

_MAJOR_ROAD_KEYWORDS = [
    "Expressway", "Express Way", "Highway", "Grand Trunk Road", "GT Road",
    "National Highway", "State Highway",
]

_MIN_STEP_M = 300   # discard lane-changes, ramps, u-turns


# ── Public entry point ────────────────────────────────────────────────────────

def filter_route(
    raw_result: dict,
    origin: str,
    destination: str,
    via: list[str] | None = None,
) -> dict:
    """
    Convert raw Mappls get_directions() result into travel_context.

    Args:
        raw_result  : dict returned by mappls.get_directions()
        origin      : lowercase city name
        destination : lowercase city name
        via         : optional intermediate cities

    Returns:
        travel_context dict
    """
    if not raw_result or not raw_result.get("routes"):
        return _empty_context(origin, destination, via)

    route     = raw_result["routes"][0]
    total_km  = round(route["distance_m"] / 1000, 1)
    total_min = round(route["duration_s"] / 60)

    # has_toll comes directly from the API's contains_classes field
    classes  = raw_result["routes"][0].get("contains_classes", {})
    has_toll = bool(classes.get("toll", 0))

    full_coords = decode(route.get("geometry", ""), precision=6)
    cum_km      = _build_cumulative_km(full_coords)
    steps       = route.get("steps", [])

    corridors = _extract_corridors(steps)
    cities    = _extract_cities(full_coords, cum_km)

    geometry_sample = [s["coords"] for s in sample(full_coords, every_km=40)] if full_coords else []
    checkpoints     = _build_checkpoints(origin, destination, cities, full_coords, cum_km, total_km)

    return {
        "trip_summary": {
            "origin":        origin,
            "destination":   destination,
            "via":           via or [],
            "total_km":      total_km,
            "duration_hr":   round(total_min / 60, 1),
            "total_eta_min": total_min,
            "has_toll":      has_toll,
        },
        "major_corridors": corridors,
        "major_cities":    cities,

        # legacy fields downstream agents read
        "origin":       origin,
        "destination":  destination,
        "via":          via or [],
        "total_km":     total_km,
        "total_eta_min": total_min,
        "geometry":     geometry_sample,
        "checkpoints":  checkpoints,
        "route_source": "mappls",
        "status":       "planned",
    }


# ── Corridor extraction ───────────────────────────────────────────────────────

def _is_major_road(name: str) -> bool:
    return any(kw.lower() in name.lower() for kw in _MAJOR_ROAD_KEYWORDS)


def _extract_corridors(steps: list[dict]) -> list[dict]:
    """
    Walk steps tracking cumulative km, group consecutive steps on the same
    major road. Merge gaps of ≤5 km between segments of the same road.
    """
    cum_km = 0.0
    spans  = {}  # road_name → {"km_start", "km_end"}

    for step in steps:
        name    = step.get("name", "").strip()
        dist_km = step.get("distance_m", 0) / 1000

        if name and _is_major_road(name):
            if name not in spans:
                spans[name] = {"km_start": cum_km, "km_end": cum_km + dist_km}
            else:
                gap = cum_km - spans[name]["km_end"]
                if gap <= 5.0:
                    spans[name]["km_end"] = cum_km + dist_km
                else:
                    spans[f"{name}*"] = {"km_start": cum_km, "km_end": cum_km + dist_km}

        cum_km += dist_km

    corridors = []
    for name, span in spans.items():
        clean_name = name.rstrip("*")
        length_km  = round(span["km_end"] - span["km_start"], 1)
        if length_km >= 5.0:
            corridors.append({
                "name":      clean_name,
                "km_start":  round(span["km_start"], 1),
                "km_end":    round(span["km_end"], 1),
                "length_km": length_km,
            })

    corridors.sort(key=lambda c: c["km_start"])
    return corridors


# ── City extraction ───────────────────────────────────────────────────────────

def _extract_cities(
    full_coords: list[tuple],
    cum_km: list[float],
    sample_every_km: int = 20,
) -> list[dict]:
    """
    Sample the route every sample_every_km km, batch reverse-geocode all
    points at once using the offline GeoNames dataset (reverse_geocoder).
    No API calls, no cost, instant.
    """
    if not full_coords:
        return []

    total  = cum_km[-1] if cum_km else 0
    points = []
    km     = 0.0
    while km <= total:
        idx = _nearest_idx(cum_km, km)
        points.append((full_coords[idx], cum_km[idx]))
        km += sample_every_km

    coords_only = [pt for pt, _ in points]
    geo_results = rg.search(coords_only, verbose=False)

    seen   = set()
    cities = []
    for (pt, pt_km), r in zip(points, geo_results):
        name = r.get("name", "").strip().lower()
        if name and name not in seen:
            seen.add(name)
            cities.append({
                "name":          name,
                "km_from_start": round(pt_km, 1),
                "coords":        pt,
            })

    cities.sort(key=lambda c: c["km_from_start"])
    return cities


# ── Checkpoint builder (legacy format for downstream agents) ──────────────────

def _build_checkpoints(
    origin: str,
    destination: str,
    cities: list[dict],
    full_coords: list[tuple],
    cum_km: list[float],
    total_km: float,
) -> list[dict]:
    """
    Build the legacy checkpoints list: origin + major cities + destination.
    Each entry has weather/places slots for downstream agents to fill.
    """
    origin_coords = full_coords[0]  if full_coords else (0.0, 0.0)
    dest_coords   = full_coords[-1] if full_coords else (0.0, 0.0)

    def _cp(name, coords, km, cp_type, note=""):
        return {
            "name":          name,
            "coords":        coords,
            "km_from_start": km,
            "type":          cp_type,
            "note":          note,
            "weather":       None,
            "places":        [],
        }

    middle = [
        _cp(c["name"], c["coords"], c["km_from_start"], "major_city")
        for c in cities
        if c["name"] not in (origin, destination)
    ]

    return (
        [_cp(origin, origin_coords, 0.0, "origin", "Start of journey")]
        + middle
        + [_cp(destination, dest_coords, round(total_km, 1), "destination", "You have arrived")]
    )


# ── Geometry helpers ──────────────────────────────────────────────────────────

def _build_cumulative_km(coords: list[tuple]) -> list[float]:
    if not coords:
        return []
    cum = [0.0]
    for i in range(1, len(coords)):
        cum.append(cum[-1] + haversine_km(coords[i - 1], coords[i]))
    return cum


def _nearest_idx(cum_km: list[float], target_km: float) -> int:
    best_idx, best_diff = 0, float("inf")
    for i, km in enumerate(cum_km):
        diff = abs(km - target_km)
        if diff < best_diff:
            best_diff = diff
            best_idx  = i
    return best_idx


# ── Empty fallback ────────────────────────────────────────────────────────────

def _empty_context(origin: str, destination: str, via: list | None = None) -> dict:
    return {
        "trip_summary":    {"origin": origin, "destination": destination, "via": via or [],
                            "total_km": None, "duration_hr": None, "total_eta_min": None, "has_toll": False},
        "major_corridors": [],
        "major_cities":    [],
        "origin":          origin,
        "destination":     destination,
        "via":             via or [],
        "total_km":        None,
        "total_eta_min":   None,
        "geometry":        [],
        "checkpoints":     [],
        "route_source":    "estimated",
        "status":          "planned",
    }
