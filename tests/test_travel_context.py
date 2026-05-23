"""
tests/test_travel_context.py
-----------------------------
Step 2 of 2: Apply the deterministic route filter and display travel_context.

If raw_route_{source}_{destination}.json exists on disk, reads it directly
(no API call). Otherwise fetches from Mappls first, then applies the filter.

Run:
    python3 tests/test_travel_context.py
    python3 tests/test_travel_context.py --from Delhi --to Jaipur
"""

import asyncio
import argparse
import json
import os
from helpers import header, ok, err, skip, dim, HDR, END
from test_fetch_raw import raw_route_path


async def fetch_and_save(source: str, destination: str, out_path: str) -> dict | None:
    """Call test_fetch_raw logic to get true raw JSON and save it."""
    import httpx
    from tools.geocoder import geocode_sync
    from config import MAPPLS_KEY

    origin_coords = geocode_sync(source)
    dest_coords   = geocode_sync(destination)
    if not origin_coords or not dest_coords:
        err(f"Could not geocode '{source}' or '{destination}'")
        return None

    o_lat, o_lon = origin_coords
    d_lat, d_lon = dest_coords
    coord_str = f"{o_lon},{o_lat};{d_lon},{d_lat}"
    url = f"https://route.mappls.com/route/direction/route_adv/driving/{coord_str}"
    params = {"alternatives": "false", "steps": "true",
              "geometries": "polyline6", "overview": "full", "access_token": MAPPLS_KEY}

    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
        resp = await client.get(url, params=params)

    if resp.status_code != 200:
        err(f"Mappls API returned HTTP {resp.status_code}")
        return None

    raw = resp.json()
    with open(out_path, "w") as f:
        json.dump(raw, f, indent=2)
    ok(f"Fetched and saved → {out_path}")
    return raw


async def run(source: str, destination: str):
    from tools.route_filter import filter_route

    print(f"\n{HDR}Travel Context: {source.title()} → {destination.title()}{END}")
    print("=" * 60)

    # ── Step 1: Load or fetch raw JSON ───────────────────────────
    header("Step 1 — Raw route JSON")

    out_path = raw_route_path(source, destination)

    if os.path.exists(out_path):
        with open(out_path) as f:
            raw = json.load(f)
        size_kb = os.path.getsize(out_path) / 1024
        ok(f"Loaded from disk: {os.path.basename(out_path)} ({size_kb:.0f} KB)")
        dim(f"  (delete this file to force a fresh API call)")
    else:
        skip(f"No cached file found — fetching from Mappls")
        raw = await fetch_and_save(source, destination, out_path)
        if not raw:
            return

    # True raw JSON uses route["distance"] and steps nested under legs
    route     = raw["routes"][0]
    all_steps = [s for leg in route.get("legs", []) for s in leg.get("steps", [])]
    km        = route["distance"] / 1000
    hrs       = int(route["duration"] // 3600)
    mins      = int((route["duration"] % 3600) // 60)

    ok(f"Raw steps     : {len(all_steps)}")
    ok(f"Raw distance  : {km:.1f} km")
    ok(f"Raw duration  : {hrs}h {mins}m")
    ok(f"Geometry size : {len(route.get('geometry',''))} chars (polyline6)")

    # ── Step 2: Apply deterministic filter ───────────────────────
    header("Step 2 — Applying deterministic route filter")

    # filter_route expects the mappls.py normalized format, so we normalise inline
    normalised = {
        "routes": [{
            "geometry":   route.get("geometry", ""),
            "distance_m": round(route["distance"]),
            "duration_s": round(route["duration"]),
            "has_toll":   route.get("toll", 0) > 0,
            "steps": [
                {
                    "name":       (s.get("name") or "").strip() or "Unnamed road",
                    "distance_m": round(s.get("distance", 0)),
                    "duration_s": round(s.get("duration", 0)),
                }
                for s in all_steps
            ],
        }]
    }

    ctx = filter_route(normalised, source.lower(), destination.lower())

    ok("Filter applied — no LLM, no API call")

    # ── Step 3: Display travel_context ───────────────────────────

    # 3a. Trip summary
    header("Trip Summary")
    s = ctx["trip_summary"]
    print(f"  {'Origin':<20} {s['origin'].title()}")
    print(f"  {'Destination':<20} {s['destination'].title()}")
    print(f"  {'Distance':<20} {s['total_km']} km")
    print(f"  {'Duration':<20} {s['duration_hr']} hrs  ({s['total_eta_min']} min)")
    print(f"  {'Has toll':<20} {s['has_toll']}")

    # 3b. Major corridors
    header("Major Corridors")
    corridors = ctx["major_corridors"]
    if corridors:
        print(f"  {'CORRIDOR':<40} {'FROM':>6}  {'TO':>6}  {'LEN':>6}")
        print(f"  {'—'*40}  {'—'*6}  {'—'*6}  {'—'*6}")
        for c in corridors:
            print(f"  {c['name']:<40} {c['km_start']:>6.0f}  {c['km_end']:>6.0f}  {c['length_km']:>5.0f}km")
    else:
        skip("No major corridors detected")

    # 3c. Major cities
    header("Major Cities (travel anchors)")
    cities = ctx["major_cities"]
    if cities:
        print(f"  {'CITY':<20} {'KM FROM START':>14}")
        print(f"  {'—'*20}  {'—'*14}")
        for c in cities:
            print(f"  {c['name'].title():<20} {c['km_from_start']:>12.1f} km")
    else:
        skip("No major cities detected")

    # 3d. Legacy checkpoints (origin + cities + destination)
    header("Checkpoints (legacy format for downstream agents)")
    checkpoints = ctx.get("checkpoints", [])
    type_icons = {"origin": "🚗", "major_city": "🏙 ", "destination": "🏁"}
    if checkpoints:
        print(f"  {'KM':>6}  {'TYPE':<14}  CHECKPOINT")
        print(f"  {'—'*6}  {'—'*14}  {'—'*30}")
        for cp in checkpoints:
            icon = type_icons.get(cp["type"], "📍")
            print(f"  {cp['km_from_start']:>6.0f}  {icon} {cp['type']:<12}  {cp['name'].title()}")
    else:
        skip("No checkpoints")

    # ── Step 4: Summary stats ─────────────────────────────────────
    header("Filter Summary")
    print(f"  Raw steps input     : {len(all_steps)}")
    print(f"  Major corridors out : {len(corridors)}")
    print(f"  Major cities out    : {len(cities)}")
    print(f"  Checkpoints out     : {len(checkpoints)}")
    compression = (1 - len(corridors) / max(len(all_steps), 1)) * 100
    print(f"\n  Compression : {len(all_steps)} steps → {len(corridors)} corridors  ({compression:.0f}% noise removed)")

    # ── Save travel_context JSON to disk ─────────────────────────
    ctx_path = out_path.replace("raw_route_", "travel_context_")
    with open(ctx_path, "w") as f:
        json.dump(ctx, f, indent=2, default=str)
    print(f"\n  Saved → {os.path.basename(ctx_path)}")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Display filtered travel_context")
    parser.add_argument("--from", dest="source",      default="Delhi",  metavar="CITY")
    parser.add_argument("--to",   dest="destination", default="Manali", metavar="CITY")
    args = parser.parse_args()

    asyncio.run(run(args.source, args.destination))
