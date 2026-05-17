# Cleanup Plan — Replace ORS with Mappls

## Context

We switched from ORS (OpenRouteService) to Mappls for routing because ORS
gave wrong ETAs for Indian roads. Mappls correctly returned ~8.25 hours for
Delhi → Manali vs ORS's wrong 6h 56m.

`tools/mappls.py` is already written and working.
This plan removes all leftover ORS and Google Maps references cleanly.

There is no Google Maps code in the project yet — a plan existed to add it
but it was never implemented. The only cleanup needed is ORS references.

---

## Files to DELETE entirely

These files have no purpose after the switch:

```
backend/tools/ors.py       ← entire ORS wrapper, replaced by mappls.py
backend/tools/routes.py    ← old route tool with hardcoded ORS API key inside
```

**How to delete:**
```bash
cd backend
rm tools/ors.py
rm tools/routes.py
```

---

## Files to EDIT

### 1. `backend/config.py`

**Remove** the ORS_KEY line entirely:
```python
# DELETE this line:
ORS_KEY = os.getenv("ORS_KEY", "")      # openrouteservice.org — free (fallback)
```

**Keep** everything else. Final config.py should look like:
```python
import os
from dotenv import load_dotenv

load_dotenv()

LLM_ENDPOINT = os.getenv("LLM_ENDPOINT", "http://localhost:11434")
LLM_MODEL    = os.getenv("LLM_MODEL", "qwen2.5")

GOOGLE_PLACES_KEY = os.getenv("GOOGLE_PLACES_KEY", "")
MAPPLS_KEY        = os.getenv("MAPPLS_KEY", "")
SESSION_TTL       = int(os.getenv("SESSION_TTL", 1800))
```

---

### 2. `backend/.env.example`

**Remove** the ORS_KEY block:
```
# DELETE these two lines:
# OpenRouteService — fallback geocoding, free at openrouteservice.org
ORS_KEY=
```

**Final `.env.example`:**
```
LLM_ENDPOINT=http://localhost:11434
LLM_MODEL=qwen2.5

# Mappls (MapmyIndia) — India routing, get key at developer.mappls.com
MAPPLS_KEY=

# Google Places — for dhabas/hotels search (needed for places agent later)
GOOGLE_PLACES_KEY=

SESSION_TTL=1800
```

---

### 3. `backend/tools/geocoder.py`

ORS is used here as the API fallback for geocoding unknown cities.
Since we're removing ORS, replace the geocoding fallback with Nominatim
(OpenStreetMap's free geocoder — no key, no auth, works for Indian cities).

**Change the import at the top:**
```python
# DELETE this line:
from tools.ors import geocode as _ors_geocode
```

**Add Nominatim geocoding function directly in geocoder.py:**
```python
import httpx

async def _nominatim_geocode(place: str) -> tuple[float, float] | None:
    """
    Free geocoding via Nominatim (OpenStreetMap).
    No API key needed. Biased to India with countrycodes=in.
    Rate limit: 1 request/second — fine for our usage.
    """
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                "https://nominatim.openstreetmap.org/search",
                params={
                    "q":            place,
                    "format":       "json",
                    "countrycodes": "in",
                    "limit":        1,
                },
                headers={"User-Agent": "travel-agent-dev/1.0"},
            )
            resp.raise_for_status()
            results = resp.json()
            if results:
                return (float(results[0]["lat"]), float(results[0]["lon"]))
    except Exception as e:
        print(f"[geocoder] Nominatim failed for '{place}': {e}")
    return None
```

**Update the `geocode()` function body:**
```python
async def geocode(place: str) -> tuple[float, float] | None:
    key = place.lower().strip()

    # Layer 1: exact match in static dict (instant)
    if key in CITY_COORDS:
        return CITY_COORDS[key]

    # Layer 2: Nominatim free geocoding (no key needed)
    result = await _nominatim_geocode(place)
    if result:
        return result

    # Layer 3: partial string match in static dict
    for city, coords in CITY_COORDS.items():
        if key in city or city in key:
            return coords

    return None
```

**Also update the docstring at top of file:**
```python
"""
tools/geocoder.py
-----------------
Place name → (lat, lon) with three fallback layers:

  1. Static dict  — instant, covers ~86 Indian cities and highway stops
  2. Nominatim    — OpenStreetMap geocoding, free, no key needed
  3. Partial match — fuzzy match against static dict
"""
```

---

### 4. `backend/agents/route_agent.py`

Several places still say "ORS" in comments and variable names. These are
cosmetic but should be cleaned up for clarity.

**Change A — docstring at top of file:**
```python
# Find:
#   3. Call ORS Directions API → route geometry + steps
# Replace with:
#   3. Call Mappls Directions API → route geometry + steps
```

**Change B — variable name in handle():**
```python
# Find:
ors_result = await get_directions(
# Replace with:
mappls_result = await get_directions(
```

**Change C — _build_trip_context() signature and body:**
```python
# Find in function signature:
    async def _build_trip_context(
        self,
        origin: str,
        destination: str,
        via: list[str],
        origin_coords: tuple,
        dest_coords: tuple,
        ors_result: dict | None,       # ← change this
    ) -> dict:

# Replace with:
    async def _build_trip_context(
        self,
        origin: str,
        destination: str,
        via: list[str],
        origin_coords: tuple,
        dest_coords: tuple,
        mappls_result: dict | None,    # ← updated name
    ) -> dict:
```

**Change D — inside _build_trip_context():**
```python
# Find (3 occurrences):
        if ors_result and ors_result.get("routes"):
            route     = ors_result["routes"][0]
            ...
            context["route_source"]  = "ors"
            ...
        # ORS unavailable — estimate from haversine + static cities

# Replace with:
        if mappls_result and mappls_result.get("routes"):
            route     = mappls_result["routes"][0]
            ...
            context["route_source"]  = "mappls"
            ...
        # Mappls unavailable — estimate from haversine + static cities
```

**Change E — the call in handle() that passes ors_result:**
```python
# Find:
        trip_context = await self._build_trip_context(
            origin, destination, via,
            origin_coords, dest_coords,
            ors_result,
        )

# Replace with:
        trip_context = await self._build_trip_context(
            origin, destination, via,
            origin_coords, dest_coords,
            mappls_result,
        )
```

**Change F — comment in _identify_checkpoints():**
```python
# Find:
        Build checkpoints from ORS road segments.
# Replace with:
        Build checkpoints from Mappls road segments.
```

**Change G — comment in _cities_as_checkpoints():**
```python
# Find:
        Fallback when ORS steps aren't available.
# Replace with:
        Fallback when Mappls steps aren't available.
```

---

### 5. `backend/test_route_agent.py`

The test file still imports from `tools.ors` and tests ORS-specific things.
Replace the live API test section entirely.

**Change the docstring at top:**
```python
# Find:
Run without ORS key  : python3 test_route_agent.py
Run with ORS key     : ORS_KEY=your_key python3 test_route_agent.py
Run with Ollama up   : ORS_KEY=your_key LLM_ENDPOINT=http://localhost:11434 python3 test_route_agent.py

# Replace with:
Run without Mappls key : python3 test_route_agent.py
Run with Mappls key    : MAPPLS_KEY=your_key python3 test_route_agent.py
Run with Ollama up     : MAPPLS_KEY=your_key LLM_ENDPOINT=http://localhost:11434 python3 test_route_agent.py
```

**Replace the entire `test_ors_live()` function:**
```python
async def test_mappls_live():
    header("mappls.py — live API")
    from tools.mappls import check_key, get_directions

    status = await check_key()
    print(f"  Key status: {status['message']}")
    if not status["ok"]:
        skip("Skipping live Mappls tests — add MAPPLS_KEY to .env")
        return False

    # Directions — Delhi → Chandigarh
    result = await get_directions(
        origin=(28.6139, 77.2090),
        destination=(30.7333, 76.7794),
        alternatives=False,
        steps=True,
    )
    if result and result.get("routes"):
        r    = result["routes"][0]
        km   = r["distance_m"] / 1000
        hrs  = r["duration_s"] // 3600
        mins = (r["duration_s"] % 3600) // 60
        ok(f"Delhi → Chandigarh: {km:.0f} km, {hrs}h {mins}m")
        ok(f"Has toll: {r['has_toll']}")
        ok(f"Steps: {len(r['steps'])}")
        ok(f"Geometry length: {len(r['geometry'])} chars")

        from tools.polyline import steps_to_segments
        segs = steps_to_segments(r["steps"])
        print("\n  Road segments:")
        for s in segs[:6]:
            print(f"    km {s['km_from_start']:>6.1f}  {s['road_name'][:40]:40}  {s['distance_km']} km")
        if len(segs) > 6:
            print(f"    ... and {len(segs)-6} more")
        return True
    else:
        err("Directions call failed")
        return False
```

**Update the full integration test** — change the import and skip condition:
```python
async def test_full_route_agent():
    header("route_agent.handle — full integration")
    from agents.route_agent import RouteAgent
    from tools.mappls import check_key          # ← was tools.ors

    status = await check_key()
    if not status["ok"]:
        skip("Skipping full agent test — add MAPPLS_KEY to .env")  # ← updated message
        return
    ...
```

**Update the run block at bottom:**
```python
# Find:
    ors_ok = loop.run_until_complete(test_ors_live())
# Replace with:
    mappls_ok = loop.run_until_complete(test_mappls_live())
```

**Update the mock context in `test_route_agent_format()`:**
```python
# Find:
        "route_source":  "ors",
# Replace with:
        "route_source":  "mappls",
```

---

### 6. `backend/PLAN.md`

Update Task 1 — it currently says "Replace ORS with Google Maps".
Since we're now using Mappls, replace Task 1 entirely with:

```markdown
## Task 1 — Cleanup complete ✅

ORS has been replaced with Mappls. The following have been done:
- tools/mappls.py created (India routing, static key auth)
- tools/ors.py deleted
- tools/routes.py deleted
- config.py updated (ORS_KEY removed, MAPPLS_KEY added)
- tools/geocoder.py updated (Nominatim replaces ORS geocoding)
- agents/route_agent.py updated (imports mappls, ORS variable names cleaned)
- test_route_agent.py updated (tests Mappls live API)

Add MAPPLS_KEY to .env and run:
    python3 test_route_agent.py
```

---

## Verification

After all changes, run in this order:

**Step 1 — confirm no ORS references remain:**
```bash
grep -rn "ors\|ORS\|openrouteservice" backend/ --include="*.py" --include="*.env*"
```
Expected output: nothing (zero results)

**Step 2 — confirm no routes.py references remain:**
```bash
grep -rn "routes\.py\|from tools.routes\|import routes" backend/ --include="*.py"
```
Expected output: nothing

**Step 3 — run test suite:**
```bash
cd backend
python3 test_route_agent.py
```
Expected: all 14 offline tests pass, live tests skip cleanly if no key set

**Step 4 — verify with real key:**
```bash
# Add key to .env first, then:
python3 test_route_agent.py
```
Expected: Mappls live test shows Delhi → Chandigarh ~250km, 3-4 hours

---

## Summary of changes

| File | Action |
|---|---|
| `tools/ors.py` | DELETE |
| `tools/routes.py` | DELETE |
| `tools/mappls.py` | Already created — no changes |
| `tools/geocoder.py` | Replace ORS import with Nominatim function |
| `config.py` | Remove ORS_KEY line |
| `.env.example` | Remove ORS_KEY block |
| `agents/route_agent.py` | Rename ors_result → mappls_result, update comments |
| `test_route_agent.py` | Replace test_ors_live() with test_mappls_live() |
| `PLAN.md` | Mark Task 1 complete, update routing tool references |
