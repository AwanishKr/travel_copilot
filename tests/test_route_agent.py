"""
Test suite for the route agent and all its tools.

Run without Mappls key : python3 test_route_agent.py
Run with Mappls key    : MAPPLS_KEY=your_key python3 test_route_agent.py
Run with Ollama up     : MAPPLS_KEY=your_key LLM_ENDPOINT=http://localhost:11434 python3 test_route_agent.py
"""

import asyncio
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "backend"))


# ── Colour output helpers ────────────────────────────────────────────────────
OK  = "\033[92m✅\033[0m"
ERR = "\033[91m❌\033[0m"
SKP = "\033[93m⏭ \033[0m"
HDR = "\033[1m"
END = "\033[0m"

def header(title): print(f"\n{HDR}=== {title} ==={END}")
def ok(msg):       print(f"  {OK} {msg}")
def err(msg):      print(f"  {ERR} {msg}")
def skip(msg):     print(f"  {SKP} {msg}")


# ============================================================================
# 1. Tools — no API key needed
# ============================================================================

def test_polyline():
    header("polyline.py")
    from tools.polyline import decode, encode, sample, total_distance_km

    # Delhi → Panipat → Chandigarh → Manali rough coords
    points = [
        (28.6139, 77.2090),
        (29.3909, 76.9635),
        (30.7333, 76.7794),
        (32.2396, 77.1887),
    ]
    encoded = encode(points)
    decoded = decode(encoded)
    match = all(
        abs(decoded[i][0] - points[i][0]) < 0.0001 and
        abs(decoded[i][1] - points[i][1]) < 0.0001
        for i in range(len(points))
    )
    ok("encode → decode round-trip") if match else err("encode/decode mismatch")

    total = total_distance_km(points)
    ok(f"total_distance_km: {total:.1f} km (Delhi→Manali straight-line ×1)")

    sampled = sample(points, every_km=100)
    ok(f"sample every 100km → {len(sampled)} points")
    assert sampled[0]["km_from_start"] == 0.0,  "first point should be 0km"
    assert sampled[-1]["coords"] == points[-1], "last point should be destination"
    ok("first/last point invariants hold")


def test_geocoder():
    header("geocoder.py")
    from tools.geocoder import geocode_sync, extract_cities, CITY_COORDS

    # Exact match
    delhi = geocode_sync("delhi")
    assert delhi is not None, "delhi not found"
    assert abs(delhi[0] - 28.6139) < 0.01
    ok(f"geocode_sync('delhi') → {delhi}")

    manali = geocode_sync("manali")
    assert manali is not None
    ok(f"geocode_sync('manali') → {manali}")

    # Partial match
    result = geocode_sync("new delhi")
    ok(f"geocode_sync('new delhi') → {result}")

    # extract_cities — returns in order of appearance in text
    cities = extract_cities("Delhi to Manali via Chandigarh")
    assert cities[0] == "delhi", f"expected delhi first, got {cities}"
    assert "chandigarh" in cities, "chandigarh should be found"
    assert "manali" in cities, "manali should be found"
    ok(f"extract_cities found: {cities}")

    # Full Delhi→Manali corridor
    corridor = ["murthal", "panipat", "ambala", "chandigarh", "bilaspur", "mandi", "kullu", "manali"]
    missing  = [c for c in corridor if c not in CITY_COORDS]
    if missing:
        err(f"Missing from static dict: {missing}")
    else:
        ok(f"Full Delhi→Manali corridor in static dict: {corridor}")

    ok(f"Total cities in static dict: {len(CITY_COORDS)}")


def test_route_agent_parse():
    header("route_agent._regex_fallback (no API needed)")
    from agents.route_agent import RouteAgent

    agent   = RouteAgent()
    session = {}

    cases = [
        ("Delhi to Manali",                   "delhi",  "manali", []),
        ("Delhi to Mumbai via Pune",           "delhi",  "mumbai", ["pune"]),
        ("Delhi Agra Jaipur",                  "delhi",  "jaipur", ["agra"]),
        ("How far is Chandigarh from Delhi?",  "delhi",  "chandigarh", []),
        ("plan a trip from Jaipur to Udaipur", "jaipur", "udaipur", []),
    ]

    all_ok = True
    for query, exp_o, exp_d, exp_via in cases:
        result = agent._regex_fallback(query, {})
        got_o  = result.get("origin")
        got_d  = result.get("destination")
        got_v  = result.get("via", [])

        if got_o == exp_o and got_d == exp_d:
            ok(f"'{query}' → {got_o} → {got_d}" + (f" via {got_v}" if got_v else ""))
        else:
            err(f"'{query}' → expected {exp_o}→{exp_d}, got {got_o}→{got_d}")
            all_ok = False

    # Test session follow-up
    session = {"last_cities": ["delhi", "chandigarh", "manali"]}
    result  = agent._regex_fallback("what about the toll?", session)
    if result.get("origin") == "delhi" and result.get("destination") == "manali":
        ok("Session follow-up resolved correctly")
    else:
        err(f"Session follow-up failed: {result}")

    # Test partial origin stored in session
    session = {}
    agent._regex_fallback("starting from Delhi", session)
    # Manually simulate what handle() does
    session["partial_origin"] = "delhi"
    result = agent._regex_fallback("going to Shimla", session)
    if result.get("origin") == "delhi" and result.get("destination") == "shimla":
        ok("Partial origin follow-up resolved correctly")
    else:
        err(f"Partial origin failed: {result}")


def test_route_agent_static_summary():
    header("route_agent._static_summary")
    from agents.route_agent import RouteAgent

    agent = RouteAgent()
    mock_context = {
        "trip_summary": {
            "origin": "delhi", "destination": "manali",
            "total_km": 572.0, "duration_hr": 10.7,
            "total_eta_min": 640, "has_toll": True,
        },
        "major_corridors": [
            {"name": "NH-44", "km_start": 0, "km_end": 250, "length_km": 250},
        ],
        "semantic_checkpoints": [
            {"name": "panipat",    "km_from_start": 90,  "type": "rest_zone",   "note": "First major dhaba stop on NH-44."},
            {"name": "chandigarh", "km_from_start": 250, "type": "city",        "note": "Last big city — fill fuel here."},
            {"name": "manali",     "km_from_start": 572, "type": "destination", "note": ""},
        ],
        "toll": {"amount": 890, "highway": "NH-44 / NH-3"},
        "seasonal_warnings": ["Rohtang Pass closed (Nov–May)"],
    }

    output = agent._static_summary(mock_context)
    print()
    print(output)
    print()

    assert "Delhi"     in output, "origin missing"
    assert "Manali"    in output, "destination missing"
    assert "572"       in output, "distance missing"
    assert "890"       in output, "toll missing"
    assert "Panipat"   in output, "checkpoint missing"
    assert "Rohtang"   in output, "seasonal warning missing"
    ok("Static summary correct")


# ============================================================================
# 2. Live API tests — need Mappls key
# ============================================================================

async def test_mappls_live():
    header("mappls.py — live API")
    from tools.mappls import check_key, get_directions

    status = await check_key()
    print(f"  Key status: {status['message']}")
    if not status["ok"]:
        skip("Skipping live Mappls tests — no valid key")
        return False

    # Directions — Delhi → Chandigarh (short, fast test)
    result = await get_directions(
        origin=(28.6139, 77.2090),
        destination=(30.7333, 76.7794),
        alternatives=False,
    )
    if result and result.get("routes"):
        r   = result["routes"][0]
        km  = r["distance_m"] / 1000
        hrs = r["duration_s"] // 3600
        mins= (r["duration_s"] % 3600) // 60
        ok(f"Delhi → Chandigarh: {km:.0f} km, {hrs}h {mins}m")
        ok(f"Steps: {len(r['steps'])}")
        ok(f"Geometry length: {len(r['geometry'])} chars")

        # Show road segments (normalize keys first)
        from tools.polyline import steps_to_segments, decode
        for step in r["steps"]:
            step["distance"] = step.get("distance_m", 0)
            step["duration"] = step.get("duration_s", 0)
        segs = steps_to_segments(r["steps"])
        for seg, step in zip(segs, r["steps"]):
            geom = step.get("geometry", "")
            seg["coords"] = decode(geom, precision=6) if geom else []
        print("\n  Road segments:")
        for s in segs[:6]:
            print(f"    km {s['km_from_start']:>6.1f}  {s['road_name'][:40]:40}  {s['distance_km']} km")
        if len(segs) > 6:
            print(f"    ... and {len(segs)-6} more")
        return True
    else:
        err("Directions call failed")
        return False


# ============================================================================
# 3. Full route agent — needs Mappls + optionally Ollama
# ============================================================================

async def test_full_route_agent():
    header("route_agent.handle — full integration")
    from agents.route_agent import RouteAgent
    from tools.mappls import check_key

    status = await check_key()
    if not status["ok"]:
        skip("Skipping full agent test — no ORS key")
        return

    agent   = RouteAgent()
    session = {}

    query = f"{SOURCE} to {DESTINATION}"
    print(f"\n  Query: '{query}'")
    result = await agent.handle(query, session)

    print(f"\n  Type   : {result['type']}")
    print("\n  --- Response ---")
    print(result["text"])
    print("  ----------------")

    if result["type"] == "response":
        ok("Agent returned a response")
    elif result["type"] == "clarify":
        ok(f"Agent asked for clarification: {result['text']}")
    elif result["type"] == "error":
        err(f"Agent returned error: {result['text']}")

    # Check trip_context in session
    ctx = session.get("trip_context")
    if ctx:
        ok(f"trip_context stored in session")
        ok(f"Total km: {ctx.get('total_km')}")
        ok(f"Checkpoints: {len(ctx.get('checkpoints', []))}")
        ok(f"Route source: {ctx.get('route_source')}")
    else:
        err("trip_context not found in session")

    # Test follow-up query
    print("\n  Follow-up: 'what about the toll?'")
    result2 = await agent.handle("what about the toll?", session)
    print(f"  → {result2['text'][:120]}...")
    ok("Follow-up handled using session context")


# ============================================================================
# Run all tests
# ============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Route Agent Test Suite")
    parser.add_argument("--from", dest="source",      default="Delhi",  metavar="CITY")
    parser.add_argument("--to",   dest="destination", default="Manali", metavar="CITY")
    args = parser.parse_args()

    SOURCE      = args.source
    DESTINATION = args.destination

    print(f"\n{HDR}Route Agent Test Suite{END}")
    print(f"Route: {SOURCE} → {DESTINATION}")
    print("=" * 50)

    # Sync tests — no API key needed
    test_polyline()
    test_geocoder()
    test_route_agent_parse()
    test_route_agent_format()

    # Async / live tests
    loop = asyncio.get_event_loop()
    loop.run_until_complete(test_mappls_live())
    loop.run_until_complete(test_full_route_agent())

    print(f"\n{HDR}Done.{END}\n")
