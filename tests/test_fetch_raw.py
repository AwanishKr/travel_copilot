"""
tests/test_fetch_raw.py
------------------------
Fetches the TRUE raw JSON from the Mappls Directions API and saves it to disk.
No processing, no filtering — exactly what the API returns.

The saved file is used by test_travel_context.py so you don't
have to hit the API every time you want to test the filter.

Run:
    python3 tests/test_fetch_raw.py
    python3 tests/test_fetch_raw.py --from Delhi --to Jaipur
"""

import asyncio
import argparse
import json
import os
import httpx
from helpers import header, ok, err, dim, HDR, END


def raw_route_path(source: str, destination: str) -> str:
    slug = f"{source.lower()}_{destination.lower()}".replace(" ", "_")
    return os.path.join(os.path.dirname(__file__), f"raw_route_{slug}.json")


async def run(source: str, destination: str):
    from tools.geocoder import geocode_sync
    from config import MAPPLS_KEY

    out_path = raw_route_path(source, destination)

    print(f"\n{HDR}Fetch Raw Route: {source.title()} → {destination.title()}{END}")
    print("=" * 60)

    # ── Step 1: Geocode ──────────────────────────────────────────
    header("Step 1 — Geocoding")

    origin_coords = geocode_sync(source)
    dest_coords   = geocode_sync(destination)

    if not origin_coords:
        err(f"Could not geocode '{source}'")
        return
    if not dest_coords:
        err(f"Could not geocode '{destination}'")
        return

    ok(f"{source.title()} → {origin_coords}")
    ok(f"{destination.title()} → {dest_coords}")

    # ── Step 2: Call Mappls API directly ─────────────────────────
    header("Step 2 — Calling Mappls API (raw)")

    o_lat, o_lon = origin_coords
    d_lat, d_lon = dest_coords
    coord_str    = f"{o_lon},{o_lat};{d_lon},{d_lat}"
    url          = f"https://route.mappls.com/route/direction/route_adv/driving/{coord_str}"

    params = {
        "alternatives": "true",
        "steps":        "true",
        "geometries":   "polyline6",
        "overview":     "full",
        "access_token": MAPPLS_KEY,
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
        resp = await client.get(url, params=params)

    if resp.status_code != 200:
        err(f"Mappls API returned HTTP {resp.status_code}")
        dim(f"  {resp.text[:200]}")
        return

    raw    = resp.json()
    routes = raw.get("routes", [])

    ok(f"Status        : {raw.get('code')}")
    ok(f"Routes found  : {len(routes)}")

    for i, route in enumerate(routes):
        all_steps = [s for leg in route.get("legs", []) for s in leg.get("steps", [])]
        km   = route["distance"] / 1000
        hrs  = int(route["duration"] // 3600)
        mins = int((route["duration"] % 3600) // 60)
        major = [s["name"] for s in all_steps if s.get("name","").strip() and s.get("distance",0) > 5000]
        # deduplicate preserving order
        seen = set(); major_dedup = []
        for n in major:
            if n not in seen: seen.add(n); major_dedup.append(n)
        print(f"\n  Route {i+1}: {km:.1f} km, {hrs}h {mins}m")
        print(f"  Major roads: {' → '.join(major_dedup) or 'n/a'}")

    # ── Step 3: Save raw JSON as-is ──────────────────────────────
    header("Step 3 — Saving raw JSON")

    with open(out_path, "w") as f:
        json.dump(raw, f, indent=2)

    size_kb = os.path.getsize(out_path) / 1024
    ok(f"Saved → {out_path}")
    ok(f"File size : {size_kb:.0f} KB")
    dim(f"\n  Run next: python3 tests/test_travel_context.py --from {source} --to {destination}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch and save raw Mappls route JSON")
    parser.add_argument("--from", dest="source",      default="Delhi",  metavar="CITY")
    parser.add_argument("--to",   dest="destination", default="Manali", metavar="CITY")
    args = parser.parse_args()

    asyncio.run(run(args.source, args.destination))
