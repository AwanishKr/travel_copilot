"""
tests/test_pipeline.py
-----------------------
End-to-end pipeline test: natural language query → full trip plan.

Traces every step the system takes so you can see exactly what each
tool contributes, similar to what a maps app would give you.

Run: python3 tests/test_pipeline.py
Run custom: python3 tests/test_pipeline.py --from Delhi --to Manali
"""

import asyncio
import argparse
from helpers import header, ok, err, skip, dim, HDR, END


async def run(source: str, destination: str):
    from tools.geocoder import geocode, geocode_sync
    from tools.mappls import get_directions, check_key
    from tools.polyline import decode, sample, steps_to_segments

    print(f"\n{HDR}Pipeline Test: \"{source} to {destination}\"{END}")
    print("=" * 60)

    # ----------------------------------------------------------------
    # Step 1: Geocoding
    # ----------------------------------------------------------------
    header("Step 1 — Geocoding (city name → coordinates)")

    origin_coords = await geocode(source)
    dest_coords   = await geocode(destination)

    if not origin_coords:
        err(f"Could not geocode '{source}'")
        return
    if not dest_coords:
        err(f"Could not geocode '{destination}'")
        return

    ok(f"{source.title()} → {origin_coords}")
    ok(f"{destination.title()} → {dest_coords}")

    # ----------------------------------------------------------------
    # Step 2: Mappls routing
    # ----------------------------------------------------------------
    header("Step 2 — Mappls routing (coordinates → route)")

    key_status = await check_key()
    if not key_status["ok"]:
        err(f"Mappls key invalid: {key_status['message']}")
        return

    result = await get_directions(origin_coords, dest_coords, alternatives=False)
    if not result or not result.get("routes"):
        err("Mappls returned no routes")
        return

    r   = result["routes"][0]
    km  = r["distance_m"] / 1000
    hrs = r["duration_s"] // 3600
    min_= (r["duration_s"] % 3600) // 60

    ok(f"Distance  : {km:.1f} km")
    ok(f"Duration  : {hrs}h {min_}m")
    ok(f"Has toll  : {r.get('has_toll')}")
    ok(f"Steps     : {len(r['steps'])}")
    ok(f"Geometry  : {len(r['geometry'])} chars (polyline6)")

    # ----------------------------------------------------------------
    # Step 3: Decode geometry
    # ----------------------------------------------------------------
    header("Step 3 — Polyline decode (geometry → coordinates)")

    coords  = decode(r["geometry"], precision=6)
    sampled = sample(coords, every_km=40)

    ok(f"Decoded {len(coords)} coordinate points from polyline")
    ok(f"Sampled {len(sampled)} checkpoint locations (every 40 km)")
    dim(f"\n  Checkpoint coordinates along route:")
    for s in sampled:
        dim(f"    {s['km_from_start']:>5.0f} km  ({s['coords'][0]:.4f}, {s['coords'][1]:.4f})")

    # ----------------------------------------------------------------
    # Step 4: Road segments from steps
    # ----------------------------------------------------------------
    header("Step 4 — Road segments (steps → named highway stretches)")

    for step in r["steps"]:
        step["distance"] = step.get("distance_m", 0)
        step["duration"] = step.get("duration_s", 0)

    segs = steps_to_segments(r["steps"])
    for seg, step in zip(segs, r["steps"]):
        geom = step.get("geometry", "")
        seg["coords"] = decode(geom, precision=6) if geom else []

    # Show only segments with significant distance
    major = [s for s in segs if s["distance_km"] >= 5]
    ok(f"{len(segs)} total segments, {len(major)} with distance ≥ 5km")
    dim(f"\n  Major road segments:")
    for s in major[:12]:
        dim(f"    {s['km_from_start']:>5.0f} km  {s['road_name'][:35]:35}  {s['distance_km']:.1f} km")
    if len(major) > 12:
        dim(f"    ... and {len(major)-12} more")

    # ----------------------------------------------------------------
    # Step 5: POI Along Route (does the static key work for this API?)
    # ----------------------------------------------------------------
    header("Step 5 — Mappls POI Along Route (static key check)")

    import os, requests as _req

    api_key  = os.getenv("MAPPLS_KEY", "")
    geometry = r["geometry"]

    if not api_key:
        skip("MAPPLS_KEY not set — skipping POI Along Route test")
    else:
        poi_url = "https://atlas.mappls.com/api/places/along_route"
        try:
            resp = _req.post(
                poi_url,
                params={"access_token": api_key},
                data={
                    "geometries": "polyline6",
                    "path":       geometry,
                    "category":   "FODCOF",   # food & restaurants
                    "buffer":     "500",
                    "sort":       "",
                },
                timeout=15,
            )
            dim(f"  HTTP status : {resp.status_code}")
            if resp.status_code == 200:
                data  = resp.json()
                pois  = data.get("suggestedPOIs", [])
                ok(f"POI Along Route works with static key — {len(pois)} food stops found")
                for p in pois[:5]:
                    dim(f"    {p.get('placeName', '?'):<30}  {p.get('type', '')}")
                if len(pois) > 5:
                    dim(f"    ... and {len(pois)-5} more")
            elif resp.status_code == 401:
                skip("Static key does NOT cover POI Along Route — OAuth required")
                dim(f"  Response: {resp.text[:120]}")
            else:
                err(f"Unexpected status {resp.status_code}")
                dim(f"  Response: {resp.text[:120]}")
        except Exception as e:
            err(f"POI Along Route call failed: {e}")

    # ----------------------------------------------------------------
    # Step 6: Summary (what a maps app shows)
    # ----------------------------------------------------------------
    header("Step 6 — Summary")
    print(f"""
  {source.title()} → {destination.title()}
  ├─ Distance : {km:.1f} km
  ├─ Duration : {hrs}h {min_}m
  ├─ Toll     : {'yes' if r.get('has_toll') else 'no / unknown'}
  ├─ Route    : {len(segs)} road segments
  └─ Stops    : {len(sampled)} sampled points every 40 km
""")
    ok("Pipeline complete — all tools returned valid data")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="End-to-end pipeline test")
    parser.add_argument("--from", dest="source",      default="Delhi",  metavar="CITY")
    parser.add_argument("--to",   dest="destination", default="Manali", metavar="CITY")
    args = parser.parse_args()

    asyncio.run(run(args.source, args.destination))
