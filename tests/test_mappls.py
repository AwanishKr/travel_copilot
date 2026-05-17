"""
tests/test_mappls.py
---------------------
Tests the Mappls routing tool directly with real API calls.
Verifies the response shape matches what route_agent expects.

Requires MAPPLS_KEY in config.py.
Run: python3 tests/test_mappls.py
"""

import asyncio
from helpers import header, ok, err, skip, dim

# Fixed coords for reproducible tests
DELHI      = (28.6139, 77.2090)
CHANDIGARH = (30.7333, 76.7794)
MANALI     = (32.2396, 77.1887)
MUMBAI     = (19.0760, 72.8777)
PUNE       = (18.5204, 73.8567)


async def test_key():
    header("Mappls — key check")
    from tools.mappls import check_key
    status = await check_key()
    if status["ok"]:
        ok(status["message"])
    else:
        err(status["message"])
    return status["ok"]


async def test_short_route():
    """Delhi → Chandigarh — quick sanity check, ~270km."""
    header("Mappls — short route (Delhi → Chandigarh)")
    from tools.mappls import get_directions
    from tools.polyline import decode, steps_to_segments

    result = await get_directions(DELHI, CHANDIGARH, alternatives=False)
    if not result or not result.get("routes"):
        err("No routes returned")
        return

    r = result["routes"][0]
    km   = r["distance_m"] / 1000
    hrs  = r["duration_s"] // 3600
    mins = (r["duration_s"] % 3600) // 60

    ok(f"Distance : {km:.1f} km  (expected ~260-290)")
    ok(f"Duration : {hrs}h {mins}m  (expected ~3h 30m–5h)")
    ok(f"Steps    : {len(r['steps'])}")
    ok(f"Geometry : {len(r['geometry'])} chars")

    # Verify geometry decodes correctly with precision=6
    coords = decode(r["geometry"], precision=6)
    ok(f"Decoded  : {len(coords)} coordinate points")
    first, last = coords[0], coords[-1]
    dim(f"  start  → ({first[0]:.4f}, {first[1]:.4f})  [expect near Delhi]")
    dim(f"  end    → ({last[0]:.4f}, {last[1]:.4f})  [expect near Chandigarh]")

    # Verify step structure
    step = r["steps"][0]
    has_name = "name" in step
    has_dist = "distance_m" in step
    has_dur  = "duration_s" in step
    has_geom = "geometry" in step
    if has_name and has_dist and has_dur and has_geom:
        ok("Step shape is correct (name, distance_m, duration_s, geometry)")
    else:
        err(f"Step missing keys — got: {list(step.keys())}")

    # Show first few road segments
    for step in r["steps"]:
        step["distance"] = step.get("distance_m", 0)
        step["duration"] = step.get("duration_s", 0)
    segs = steps_to_segments(r["steps"])
    dim(f"\n  First 5 road segments:")
    for s in segs[:5]:
        dim(f"    {s['km_from_start']:>6.1f} km  {s['road_name'][:40]}")


async def test_long_route():
    """Delhi → Manali — the flagship route, ~500km mountain road."""
    header("Mappls — long route (Delhi → Manali)")
    from tools.mappls import get_directions
    from tools.polyline import decode, sample

    result = await get_directions(DELHI, MANALI, alternatives=False)
    if not result or not result.get("routes"):
        err("No routes returned")
        return

    r   = result["routes"][0]
    km  = r["distance_m"] / 1000
    hrs = r["duration_s"] // 3600
    min_= (r["duration_s"] % 3600) // 60

    ok(f"Distance : {km:.1f} km  (expected ~490-560)")
    ok(f"Duration : {hrs}h {min_}m  (expected ~8h–11h)")
    ok(f"Has toll : {r.get('has_toll')}")

    coords  = decode(r["geometry"], precision=6)
    sampled = sample(coords, every_km=40)
    ok(f"Geometry : {len(coords)} points → sampled to {len(sampled)} checkpoints (every 40km)")
    dim(f"\n  Sampled checkpoint coordinates:")
    for s in sampled:
        dim(f"    {s['km_from_start']:>5.0f} km  ({s['coords'][0]:.4f}, {s['coords'][1]:.4f})")


async def test_via_route():
    """Delhi → Manali via Chandigarh — tests waypoint support."""
    header("Mappls — via route (Delhi → Chandigarh → Manali)")
    from tools.mappls import get_directions

    result = await get_directions(DELHI, MANALI, via=[CHANDIGARH], alternatives=False)
    if not result or not result.get("routes"):
        err("No routes returned")
        return

    r  = result["routes"][0]
    km = r["distance_m"] / 1000
    ok(f"Via route distance: {km:.1f} km")
    ok(f"Steps: {len(r['steps'])}")


async def test_alternatives():
    """Mumbai → Pune — short route with multiple path options."""
    header("Mappls — alternative routes (Mumbai → Pune)")
    from tools.mappls import get_directions

    result = await get_directions(MUMBAI, PUNE, alternatives=True)
    if not result or not result.get("routes"):
        err("No routes returned")
        return

    count = len(result["routes"])
    ok(f"Returned {count} route option(s)")
    for i, r in enumerate(result["routes"]):
        km  = r["distance_m"] / 1000
        hrs = r["duration_s"] // 3600
        min_= (r["duration_s"] % 3600) // 60
        dim(f"  Option {i+1}: {km:.1f} km  {hrs}h {min_}m  toll={r.get('has_toll')}")


async def run():
    key_ok = await test_key()
    if not key_ok:
        skip("Skipping route tests — fix MAPPLS_KEY in config.py first")
        return

    await test_short_route()
    await test_long_route()
    await test_via_route()
    await test_alternatives()


if __name__ == "__main__":
    asyncio.run(run())
