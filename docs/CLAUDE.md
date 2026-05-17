# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Vision

A real-time road trip co-pilot for Indian highways. Given a route, it tells the driver every stop, weather at each checkpoint, where to eat, and what to watch out for. Not a trip planner — a knowledgeable co-driver.

## Running the Project

```bash
# Start Ollama (LLM for entity extraction + checkpoint enrichment)
ollama pull qwen2.5
ollama serve

# Set up Python environment (from project root)
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Copy and fill in environment variables
cp .env.example .env
# Add ORS_KEY, LLM_ENDPOINT, GOOGLE_PLACES_KEY

# Run tests (verifies tools + route agent end-to-end)
python3 test_route_agent.py

# Start the server
python3 main.py
# Open http://localhost:8000
```

Run tests with specific env overrides:
```bash
ORS_KEY=your_key python3 test_route_agent.py
ORS_KEY=your_key LLM_ENDPOINT=http://localhost:11434 python3 test_route_agent.py
```

## Architecture

### The `trip_context` — shared state between all agents

Every agent reads from and writes to `session["trip_context"]`. The route agent builds it; weather, places, hotels, and budget agents enrich it. This is the core architectural contract.

```python
{
    "origin": "delhi", "destination": "manali", "via": [],
    "total_km": 572.0, "total_eta_min": 640,
    "geometry": [(lat, lon), ...],      # sampled every 40km
    "checkpoints": [
        {
            "name": "panipat", "coords": (29.39, 76.96),
            "km_from_start": 90.0,
            "type": "fuel_food",        # fuel_food | major_city | gateway
                                        # mountain_critical | scenic | destination
            "note": "First major dhaba stop on NH-44.",
            "weather": None,            # filled by weather agent
            "places": [],               # filled by places agent
        }, ...
    ],
    "toll": {"amount": 890, "highway": "NH-44 / NH-3"},
    "seasonal_warnings": ["Rohtang Pass closed (Nov–May)"],
    "route_source": "ors",   # "ors" | "estimated"
    "status": "planned",     # planned | active | completed
}
```

### Agent pipeline

1. **`agents/router.py`** — 3-layer routing: keyword match → LLM classification → generic fallback. Dispatches to the right agent.
2. **`agents/base_agent.py`** — `BaseAgent`: `call_llm()`, `make_response()`, `make_error()`, `make_clarify()`. All agents inherit this.
3. **`agents/route_agent.py`** — The foundation. Parses natural language (including Hindi), geocodes, calls ORS, builds `trip_context`, enriches checkpoints via LLM, stores result in session.
4. Weather / places / hotels / budget agents — read `trip_context` and enrich checkpoint fields.

### Tool layer

- **`tools/ors.py`** — ORS Directions API (route geometry, steps, distance, duration) and ORS Geocoding (place name → coordinates). ORS uses `[lon, lat]` order; our code uses `(lat, lon)` tuples everywhere else.
- **`tools/geocoder.py`** — 86-city static dict for offline geocoding (`CITY_COORDS`). `geocode()` tries ORS first, falls back to static dict. `geocode_sync()` is the sync variant. `extract_cities()` pulls city mentions from text.
- **`tools/polyline.py`** — Polyline decode/encode, `sample()` (sample coords every N km), `steps_to_segments()` (converts ORS steps to road segments with name + km), `haversine_km()`.

### Session memory

In-memory Python dict, keyed by cookie:
- `trip_context` — full trip plan (set by route agent)
- `last_cities` — for follow-up resolution ("what about the return trip?")
- `partial_origin` — if user gives origin but not destination yet

### LLM usage

`call_llm()` in `base_agent.py` handles all LLM calls. Set `LLM_ENDPOINT` to point at Ollama (dev) or Claude API (prod) — they're API-compatible. `LLM_MODEL` defaults to `qwen2.5`.

## Environment Variables (`config.py`)

| Variable | Default | Purpose |
|---|---|---|
| `LLM_ENDPOINT` | `http://localhost:11434` | Ollama or Claude API base URL |
| `LLM_MODEL` | `qwen2.5` | Model name |
| `ORS_KEY` | — | OpenRouteService key (free at openrouteservice.org) |
| `GOOGLE_PLACES_KEY` | — | Google Places API key (for dhaba/hotel search) |
| `SESSION_TTL` | `1800` | Session timeout in seconds |

## Tech Stack

| Component | Tool | Key |
|---|---|---|
| Web framework | FastAPI + Jinja2 | — |
| LLM (dev) | Ollama + Qwen2.5 | `LLM_ENDPOINT` |
| LLM (prod) | Claude API | `LLM_ENDPOINT` |
| Routing | OpenRouteService | `ORS_KEY` |
| Geocoding | Static dict + ORS | `ORS_KEY` |
| Weather | Open-Meteo (no key needed) | — |
| Places / dhabas | Google Places | `GOOGLE_PLACES_KEY` |
| Map rendering | Leaflet + OpenStreetMap | — |

## Build Status & What's Next

See [PLAN.md](PLAN.md) for the full development plan. Current state:

- `agents/route_agent.py` ✅ — complete, sets the pattern for all other agents
- `tools/ors.py`, `tools/geocoder.py`, `tools/polyline.py` ✅
- Weather, places, hotels, budget agents — ⚠️ scaffolded, need rewrite to consume `trip_context`
- `tools/routes.py` — ❌ superseded by `ors.py`, delete it

When rewriting any agent, always check for `session.get("trip_context")` first and enrich checkpoints if a trip is active. Standalone query handling is the fallback.

## Key Files to Read Before Making Changes

1. [agents/base_agent.py](agents/base_agent.py) — BaseAgent interface
2. [agents/router.py](agents/router.py) — routing logic
3. [agents/route_agent.py](agents/route_agent.py) — reference implementation, most complex agent
4. [tools/ors.py](tools/ors.py) — all ORS API calls
5. [tools/geocoder.py](tools/geocoder.py) — city resolution
6. [tools/polyline.py](tools/polyline.py) — geometry utilities
7. [test_route_agent.py](test_route_agent.py) — run after every change to verify nothing is broken