# Travel Agent — Current State

## What exists right now

The route agent is the only completed module. Everything else is future work.

```
backend/
├── config.py
├── main.py
├── agents/
│   ├── base_agent.py
│   ├── router.py
│   ├── route_agent.py
│   └── __init__.py
└── tools/
    ├── mappls.py
    ├── geocoder.py
    └── polyline.py
```

---

## The three tools

### `tools/mappls.py`
Calls the Mappls Directions API.
- `get_directions(origin, destination, via, alternatives, steps)` — returns route geometry, distance, duration, toll flag, and turn-by-turn steps
- `check_key()` — verifies the static key works
- Auth: static key as `?access_token=` query param
- Coordinates: lon,lat order, semicolon-separated in URL
- Geometry: polyline6 format (6-digit precision) — always decode with `precision=6`

### `tools/geocoder.py`
Converts city names to coordinates.
- `geocode(place)` — async, tries static dict → Nominatim → partial match
- `geocode_sync(place)` — sync, static dict and partial match only
- `extract_cities(text)` — finds all known cities in a string, returns in order of appearance
- Static dict covers 86 Indian cities and major highway stops
- Nominatim (OpenStreetMap) used as free API fallback, no key needed

### `tools/polyline.py`
Pure geometry utilities, no network calls.
- `decode(encoded, precision)` — decodes Mappls/Google encoded polyline to list of (lat, lon)
- `encode(coords, precision)` — encodes coordinates back to polyline string
- `sample(coords, every_km)` — returns one point every N km along the route
- `steps_to_segments(steps)` — converts turn-by-turn steps to named road segments with km markers
- `haversine_km(point_a, point_b)` — straight-line distance between two coordinates
- `total_distance_km(coords)` — total length of a polyline

---

## The route agent

### `agents/route_agent.py`

**What it does:**
Takes a natural language query, plans the full trip, and stores the result
in `session["trip_context"]` for other agents to use later.

**Flow:**
1. `_extract_route()` — LLM extracts origin, destination, via from the query. Falls back to `_regex_fallback()` if Ollama is unavailable.
2. `_geocode_all()` — geocodes all places concurrently
3. `get_directions()` — calls Mappls, returns geometry + steps
4. `_build_trip_context()` — assembles the full trip context dict
5. `_identify_checkpoints()` — finds meaningful stops from road segment transitions
6. `_enrich_checkpoints()` — LLM adds type and local knowledge note per checkpoint
7. Returns formatted trip briefing to user

**trip_context shape** (stored in `session["trip_context"]`):
```python
{
    "origin":        "delhi",
    "destination":   "manali",
    "via":           [],
    "total_km":      497.4,
    "total_eta_min": 495,          # ~8h 15m — Mappls gives realistic Indian ETAs
    "geometry":      [(lat, lon), ...],   # sampled every 40km
    "checkpoints": [
        {
            "name":          "panipat",
            "coords":        (29.39, 76.96),
            "km_from_start": 90.0,
            "type":          "fuel_food",
            "note":          "First major dhaba stop on NH-44.",
            "weather":       None,    # filled by weather agent later
            "places":        [],      # filled by places agent later
        },
        ...
    ],
    "toll":              {"amount": 890, "highway": "NH-44 / NH-3"},
    "seasonal_warnings": ["Rohtang Pass closed (Nov–May)"],
    "route_source":      "mappls",
    "status":            "planned",
}
```

**Checkpoint types:**
- `fuel_food` — dhaba or food stop, fuel available
- `major_city` — ATM, hospital, last highway amenities
- `gateway` — road character changes here
- `mountain_critical` — weather and road conditions become critical
- `scenic` — viewpoint or photo stop
- `destination` — final stop

**Query patterns handled:**
- "Delhi to Manali"
- "Delhi to Mumbai via Pune"
- "Delhi Agra Jaipur" (multi-stop)
- "How far is Chandigarh from Delhi?" (from/to swap)
- "what about the toll?" (session follow-up)

---

## Environment

```
# backend/.env
LLM_ENDPOINT=http://localhost:11434
LLM_MODEL=qwen2.5
MAPPLS_KEY=your_static_key_here
SESSION_TTL=1800
```

---

## Running

```bash
# Start Ollama (for LLM extraction and checkpoint enrichment)
ollama pull qwen2.5
ollama serve

# Run tests
cd backend
python3 test_route_agent.py

# Start server
python3 main.py
# Open http://localhost:8000
```

---

## What's next

The `trip_context` built by the route agent is the foundation.
The next agents to build consume it:

- **Weather agent** — fetches weather for each checkpoint's coordinates
- **Places agent** — finds dhabas along the route geometry
- **Hotels agent** — finds hotels at the destination
- **Budget agent** — estimates cost using trip_context distance and toll
