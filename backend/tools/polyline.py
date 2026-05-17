"""
tools/polyline.py
-----------------
Encode and decode Google/Mappls encoded polyline format.

Mappls returns route geometry as an encoded polyline string.
This module decodes it into usable (lat, lon) coordinates.

Encoded polyline spec:
  https://developers.google.com/maps/documentation/utilities/polylinealgorithm

Two precisions supported:
  - 5-digit (1e5) : default Mappls "polyline"  param
  - 6-digit (1e6) : Mappls "polyline6" param (higher accuracy)

Usage:
    from tools.polyline import decode, sample, haversine_km

    coords = decode("osgmDutwuMjA~@vEfG...")
    # [(28.5524, 77.1311), (28.549, 77.124), ...]

    sparse = sample(coords, every_km=50)
    # one point roughly every 50 km along the route
"""

import math
from typing import Literal


# ---------------------------------------------------------------------------
# Core decode / encode
# ---------------------------------------------------------------------------

def decode(
    encoded: str,
    precision: Literal[5, 6] = 5,
) -> list[tuple[float, float]]:
    """
    Decode an encoded polyline string into a list of (lat, lon) tuples.

    Args:
        encoded   : The encoded polyline string from Mappls/Google.
        precision : 5 for standard polyline, 6 for polyline6.
                    Mappls default is 5 (param geometries=polyline).

    Returns:
        List of (latitude, longitude) float tuples.

    Example:
        >>> decode("osgmDutwuMjA~@")
        [(28.5524, 77.1311), ...]
    """
    factor   = 10 ** precision
    result   = []
    index    = 0
    lat      = 0
    lng      = 0
    length   = len(encoded)

    while index < length:
        # --- decode latitude delta ---
        shift, result_lat = 0, 0
        while True:
            b = ord(encoded[index]) - 63
            index += 1
            result_lat |= (b & 0x1F) << shift
            shift += 5
            if b < 0x20:
                break
        dlat = ~(result_lat >> 1) if (result_lat & 1) else (result_lat >> 1)
        lat += dlat

        # --- decode longitude delta ---
        shift, result_lng = 0, 0
        while True:
            b = ord(encoded[index]) - 63
            index += 1
            result_lng |= (b & 0x1F) << shift
            shift += 5
            if b < 0x20:
                break
        dlng = ~(result_lng >> 1) if (result_lng & 1) else (result_lng >> 1)
        lng += dlng

        result.append((lat / factor, lng / factor))

    return result


def encode(
    coords: list[tuple[float, float]],
    precision: Literal[5, 6] = 5,
) -> str:
    """
    Encode a list of (lat, lon) tuples into an encoded polyline string.
    Useful for sending waypoints back to Mappls or storing compactly.

    Args:
        coords    : List of (latitude, longitude) tuples.
        precision : 5 or 6 digit precision.

    Returns:
        Encoded polyline string.
    """
    factor = 10 ** precision
    output = []
    prev_lat = prev_lng = 0

    for lat, lng in coords:
        for value, prev in [
            (int(round(lat * factor)), prev_lat),
            (int(round(lng * factor)), prev_lng),
        ]:
            delta = value - prev
            delta = ~(delta << 1) if delta < 0 else delta << 1
            while delta >= 0x20:
                output.append(chr((0x20 | (delta & 0x1F)) + 63))
                delta >>= 5
            output.append(chr(delta + 63))

        prev_lat = int(round(lat * factor))
        prev_lng = int(round(lng * factor))

    return "".join(output)


# ---------------------------------------------------------------------------
# Geometry utilities
# ---------------------------------------------------------------------------

def haversine_km(
    point_a: tuple[float, float],
    point_b: tuple[float, float],
) -> float:
    """
    Great-circle distance between two (lat, lon) points in kilometres.
    Fast enough to call in a loop over thousands of polyline points.
    """
    lat1, lon1 = map(math.radians, point_a)
    lat2, lon2 = map(math.radians, point_b)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371.0 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def total_distance_km(coords: list[tuple[float, float]]) -> float:
    """Total length of a polyline in kilometres."""
    return sum(
        haversine_km(coords[i], coords[i + 1])
        for i in range(len(coords) - 1)
    )


def sample(
    coords: list[tuple[float, float]],
    every_km: float = 50.0,
) -> list[dict]:
    """
    Walk the polyline and pick one representative point every `every_km`
    kilometres. Always includes the first and last point.

    Returns a list of dicts:
        [
            {"coords": (lat, lon), "km_from_start": 0.0},
            {"coords": (lat, lon), "km_from_start": 51.3},
            ...
            {"coords": (lat, lon), "km_from_start": 571.8},
        ]

    This is the feed for reverse geocoding — we pass these to Mappls
    reverse geocode to find which city/town each sample point is near.
    """
    if not coords:
        return []

    samples      = [{"coords": coords[0], "km_from_start": 0.0}]
    accumulated  = 0.0   # km since last sample
    total_so_far = 0.0   # km from route start

    for i in range(1, len(coords)):
        seg_km       = haversine_km(coords[i - 1], coords[i])
        accumulated  += seg_km
        total_so_far += seg_km

        if accumulated >= every_km:
            samples.append({
                "coords":        coords[i],
                "km_from_start": round(total_so_far, 1),
            })
            accumulated = 0.0

    # Always include the destination
    last = {"coords": coords[-1], "km_from_start": round(total_so_far, 1)}
    if samples[-1]["coords"] != coords[-1]:
        samples.append(last)

    return samples


def steps_to_segments(steps: list[dict]) -> list[dict]:
    """
    Convert Mappls turn-by-turn steps into route segments.
    Each segment = one named road stretch.

    Input (from Mappls steps response):
        [
            {"name": "NH-44", "distance": 87000, "duration": 3600, "geometry": "..."},
            {"name": "Kiratpur-Nerchowk Expressway", "distance": 63000, ...},
            ...
        ]

    Output:
        [
            {
                "road_name":   "NH-44",
                "distance_km": 87.0,
                "duration_min": 60,
                "coords":      [(lat, lon), ...],   # decoded from step geometry
                "km_from_start": 0.0,
            },
            ...
        ]

    Road name changes are natural checkpoint boundaries — where the
    character of the drive changes (flat highway → mountain road etc.)
    """
    segments     = []
    km_so_far    = 0.0

    for step in steps:
        name     = (step.get("name") or "").strip() or "Unnamed road"
        dist_km  = round(step.get("distance", 0) / 1000, 1)
        dur_min  = round(step.get("duration", 0) / 60)
        geom     = step.get("geometry", "")

        coords = decode(geom) if geom else []

        segments.append({
            "road_name":     name,
            "distance_km":   dist_km,
            "duration_min":  dur_min,
            "coords":        coords,
            "km_from_start": round(km_so_far, 1),
        })
        km_so_far += dist_km

    return segments
