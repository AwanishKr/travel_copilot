# Travel Agent — Claude Code Plan

## Context

This is a FastAPI + Jinja2 web app — a real-time road trip co-pilot for
Indian highways. The user types a route ("Delhi to Manali") and gets a full
trip briefing: distance, realistic ETA, checkpoints along the way, weather
at each stop, dhabas to eat at, hotels at the destination.

The architecture uses a multi-agent system:
- A central router classifies the user's query and dispatches to the right agent
- Each specialist agent owns one domain (route, weather, places, hotels, budget)
- All agents share a `trip_context` stored in session (built by route_agent)
- The LLM (Ollama locally, Claude API in production) is used for entity
  extraction and enrichment — not for answering factual questions

**Read these files first before making any changes:**
1. `agents/base_agent.py` — BaseAgent interface
2. `agents/router.py` — 3-layer routing logic
3. `agents/route_agent.py` — most complete agent, sets the pattern
4. `tools/polyline.py` — geometry utilities (don't touch, fully tested)
5. `tools/geocoder.py` — city resolution (don't touch, fully tested)

---

## Current file status

```
backend/
├── config.py                ✅ keep, needs GOOGLE_MAPS_KEY added
├── main.py                  ✅ keep as-is
├── agents/
│   ├── base_agent.py        ✅ keep as-is
│   ├── router.py            ✅ keep as-is
│   ├── route_agent.py       ✅ keep, one small fix needed (see Task 2)
│   ├── weather_agent.py     ⚠️  rewrite (see Task 4)
│   ├── places_agent.py      ⚠️  rewrite (see Task 5)
│   ├── hotels_agent.py      ⚠️  rewrite (see Task 5)
│   ├── budget_agent.py      ⚠️  rewrite (see Task 6)
│   └── __init__.py          ✅ keep, add new agents here when done
└── tools/
    ├── polyline.py          ✅ keep as-is — fully tested, do not modify
    ├── geocoder.py          ✅ keep as-is — fully tested, do not modify
    ├── google_maps.py       ❌ does not exist yet — Task 1 creates this
    ├── weather.py           ⚠️  rewrite (see Task 3)
    ├── ors.py               ❌ delete after Task 1 is done
    ├── routes.py            ❌ delete immediately — superseded by google_maps.py
    └── places.py            ⚠️  rewrite (see Task 5)
```

---

## Task 1 — Replace ORS with Google Maps (do this first)

**Why:** ORS gives wrong ETAs for Indian roads (estimates 77 km/h avg on
mountain roads). Google Maps uses real traffic data from Android devices and
knows Indian road speeds correctly.

**Setup:**
1. Go to `console.cloud.google.com`
2. Create a project → Enable these APIs:
   - Directions API
   - Geocoding API
   - Places API (New)
3. Create credentials → API key → copy it
4. Add to `backend/.env`: `GOOGLE_MAPS_KEY=your_key_here`
5. Add to `config.py`: `GOOGLE_MAPS_KEY = os.getenv("GOOGLE_MAPS_KEY", "")`

**Create `tools/google_maps.py` with these functions:**

```python
async def get_directions(
    origin: tuple[float, float],
    destination: tuple[float, float],
    via: list[tuple[float, float]] | None = None,
) -> dict | None:
    """
    Call Google Maps Directions API.

    Endpoint:
        GET https://maps.googleapis.com/maps/api/directions/json
        ?origin={lat},{lon}
        &destination={lat},{lon}
        &waypoints={lat},{lon}|{lat},{lon}   (optional)
        &mode=driving
        &region=in
        &key={GOOGLE_MAPS_KEY}

    Returns same shape as old ors.get_directions() so nothing else changes:
    {
        "routes": [
            {
                "geometry":   "encoded_polyline_string",
                "distance_m": 572000,
                "duration_s": 38400,   # Google gives realistic Indian ETAs
                "steps": [
                    {
                        "name":        "NH-44",
                        "distance_m":  87000,
                        "duration_s":  4500,
                        "instruction": "Continue onto NH-44",
                        "geometry":    "encoded_polyline_string",
                    },
                    ...
                ],
            }
        ]
    }

    Google Maps notes:
    - overview_polyline.points = full route geometry (encoded polyline)
    - legs[].steps[].polyline.points = step geometry
    - legs[].steps[].html_instructions = strip HTML tags for plain text
    - legs[].distance.value = metres
    - legs[].duration_in_traffic.value = seconds (with traffic, use this)
    - legs[].duration.value = seconds (without traffic, fallback)
    - Use duration_in_traffic if available, else duration
    - region=in biases results to India
    """
```

```python
async def geocode(place: str) -> tuple[float, float] | None:
    """
    Call Google Geocoding API.

    Endpoint:
        GET https://maps.googleapis.com/maps/api/geocode/json
        ?address={place}
        &region=in
        &key={GOOGLE_MAPS_KEY}

    Returns (lat, lon) or None.
    Parse: results[0].geometry.location.{lat, lng}
    """
```

```python
async def check_key() -> dict:
    """Geocode 'Delhi' and return ok/error status."""
```

**After creating google_maps.py:**
- Update `tools/geocoder.py` line that imports from ors:
  ```python
  # Change this:
  from tools.ors import geocode as _ors_geocode
  # To this:
  from tools.google_maps import geocode as _api_geocode
  ```
- Update `agents/route_agent.py` import:
  ```python
  # Change this:
  from tools.ors import get_directions
  # To this:
  from tools.google_maps import get_directions
  ```
- Delete `tools/ors.py`
- Delete `tools/routes.py`

**Verify with:**
```bash
python3 -c "
import asyncio
from tools.google_maps import check_key
print(asyncio.run(check_key()))
"
```

Then run `python3 test_route_agent.py` — all tests should still pass.

---

## Task 2 — Fix checkpoint detection in route_agent.py

**The problem:** `_identify_checkpoints()` only returns origin and destination,
missing all intermediate stops like Panipat, Chandigarh, Mandi, Kullu.

**Why it's broken:** The function calls `_nearest_known_city(seg["coords"], ...)`
but `seg["coords"]` is always empty — `steps_to_segments()` in `polyline.py`
decodes step geometry, but Google Maps steps include step geometry in
`polyline.points` which needs to be decoded first before passing to
`steps_to_segments()`.

**The fix in `route_agent.py`:**

In `_build_trip_context()`, after getting directions, decode the step
geometries before passing to `steps_to_segments()`:

```python
# Before calling steps_to_segments, decode each step's geometry
for step in route["steps"]:
    if step.get("geometry"):
        step["coords"] = decode(step["geometry"])
    else:
        step["coords"] = []

segments = steps_to_segments(route["steps"])
```

Then in `_nearest_known_city()`, the `coords_list` will actually have points
and the city matching will work.

**Also reduce MIN_SEGMENT_KM from 30 to 15** — some important stops like
Murthal are close together but still meaningful checkpoints.

**Expected result after fix:**
```
Delhi → Manali
Checkpoints:
     0 km  🍽 Delhi
    90 km  🍽 Panipat
   155 km  🍽 Ambala
   250 km  🏙 Chandigarh
   380 km  🚧 Bilaspur
   460 km  🚧 Mandi
   510 km  ⛰ Kullu
   533 km  🏁 Manali
```

---

## Task 3 — Rewrite tools/weather.py

**Replace the existing file entirely.**

Use Open-Meteo API — completely free, no API key, no registration.

```python
async def get_weather_coords(
    coords: tuple[float, float]
) -> dict | None:
    """
    Get current weather + 3-day forecast for a lat/lon point.

    Endpoint:
        GET https://api.open-meteo.com/v1/forecast
        ?latitude={lat}
        &longitude={lon}
        &current=temperature_2m,weathercode,windspeed_10m,precipitation
        &daily=temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode
        &timezone=Asia/Kolkata
        &forecast_days=3

    Returns:
    {
        "temp_c":        22.5,
        "wind_kmh":      12.0,
        "precipitation": 0.0,
        "condition":     "Clear sky",       # decoded from weathercode
        "forecast": [
            {"date": "2026-05-17", "max_c": 28, "min_c": 18,
             "rain_mm": 0.0, "condition": "Partly cloudy"},
            ...
        ]
    }

    WMO Weather codes → human readable:
    0 = Clear sky, 1-3 = Partly cloudy, 45-48 = Fog,
    51-67 = Rain/drizzle, 71-77 = Snow, 80-82 = Rain showers,
    95-99 = Thunderstorm
    Include a _decode_weathercode(code) helper function.
    """


async def get_weather_city(city: str) -> dict | None:
    """
    Convenience wrapper — look up city coords then call get_weather_coords.
    Uses geocoder.geocode_sync() for coords.
    """
```

---

## Task 4 — Rewrite agents/weather_agent.py

The existing weather_agent answers isolated queries ("weather in Jaipur").
Rewrite it to also enrich the `trip_context` when a trip is planned.

```python
class WeatherAgent(BaseAgent):
    name = "weather"
    description = "Gets weather forecasts for cities or for all checkpoints on a planned route"
    keywords = [
        "weather", "rain", "temperature", "forecast", "cold", "hot",
        "fog", "mausam", "barish", "kitna thanda", "climate",
    ]

    async def handle(self, query: str, session: dict) -> dict:
        # If a trip is planned, enrich all checkpoints with weather
        if session.get("trip_context"):
            return await self._enrich_trip_weather(session, query)

        # Otherwise answer as a standalone weather query
        return await self._standalone_weather(query, session)

    async def _enrich_trip_weather(self, session, query):
        """
        Fetch weather for every checkpoint in trip_context concurrently.
        Then return a summary like:
        "Weather looks clear until Chandigarh (22°C).
         Light rain expected at Mandi (18°C, 8mm).
         Kullu and Manali will be cold and overcast (12°C)."
        """
        ctx = session["trip_context"]
        checkpoints = ctx["checkpoints"]

        # Fetch all concurrently
        results = await asyncio.gather(*[
            get_weather_coords(cp["coords"])
            for cp in checkpoints
            if cp.get("coords")
        ], return_exceptions=True)

        # Store in trip_context
        for cp, weather in zip(checkpoints, results):
            if isinstance(weather, dict):
                cp["weather"] = weather

        # Ask LLM to write a natural weather summary
        weather_summary = self._build_weather_summary(checkpoints)
        llm_summary = await self.call_llm(
            f"Summarise this weather for a road trip from "
            f"{ctx['origin'].title()} to {ctx['destination'].title()} "
            f"in 2-3 sentences, natural and conversational: {weather_summary}"
        )

        return self.make_response(llm_summary, data={"checkpoints": checkpoints})

    async def _standalone_weather(self, query, session):
        """Handle 'weather in Jaipur' type queries."""
        # Extract city from query using LLM or regex
        # Call get_weather_city()
        # Format and return
```

---

## Task 5 — Rewrite agents/places_agent.py and tools/places.py

**The vision:** Find dhabas and restaurants along the actual route geometry,
not just near the destination city.

**Rewrite `tools/places.py`:**

```python
async def search_nearby(
    coords: tuple[float, float],
    place_type: str = "restaurant",
    radius_m: int = 5000,
) -> list[dict]:
    """
    Search for places near a coordinate point using Google Places API.

    Endpoint:
        GET https://maps.googleapis.com/maps/api/place/nearbysearch/json
        ?location={lat},{lon}
        &radius={radius_m}
        &type={place_type}
        &key={GOOGLE_MAPS_KEY}

    place_type values:
        "restaurant"  — dhabas and restaurants
        "gas_station" — fuel stops
        "lodging"     — hotels (used by hotels_agent)
        "hospital"    — emergency
        "atm"         — cash

    Returns list of:
    {
        "name":    "Haveli Dhaba",
        "address": "NH-44, Murthal",
        "rating":  4.3,
        "total_ratings": 1200,
        "open_now": True,
        "coords":  (29.09, 77.01),
        "place_id": "ChIJ...",
    }
    """


async def search_along_route(
    geometry_coords: list[tuple[float, float]],
    place_type: str = "restaurant",
    sample_every_n: int = 2,
) -> list[dict]:
    """
    Search for places along a route by sampling geometry points.

    geometry_coords comes from trip_context["geometry"] — already sampled
    every 40km. Use sample_every_n=2 to search every 80km.

    Deduplicates results by place_id.
    Returns combined list sorted by position along route.
    """
```

**Rewrite `agents/places_agent.py`:**

```python
async def handle(self, query, session):
    # If trip planned → find dhabas along the route
    if session.get("trip_context"):
        return await self._places_along_route(session, query)
    # Otherwise → find places near a mentioned city
    return await self._standalone_places(query, session)

async def _places_along_route(self, session, query):
    ctx = session["trip_context"]

    # Detect what type of place user wants
    # "fuel", "petrol" → gas_station
    # "hotel", "stay"  → lodging (hotels_agent handles this)
    # default          → restaurant
    place_type = self._detect_place_type(query)

    places = await search_along_route(
        ctx["geometry"],
        place_type=place_type,
    )

    # Attach to nearest checkpoint in trip_context
    for place in places:
        nearest_cp = self._nearest_checkpoint(place["coords"], ctx["checkpoints"])
        if nearest_cp:
            nearest_cp["places"].append(place)

    # Format response
    return self.make_response(
        self._format_places(places, ctx["origin"], ctx["destination"]),
        data={"places": places}
    )
```

---

## Task 6 — Rewrite agents/budget_agent.py

Use `trip_context` instead of estimating from scratch:

```python
async def handle(self, query, session):
    ctx = session.get("trip_context")
    if not ctx:
        return self.make_clarify(
            "Plan a route first, then I can estimate the budget. "
            "Try: 'Delhi to Manali'"
        )

    # Extract people and nights from query using LLM
    params = await self._extract_params(query)
    # params = {"people": 2, "nights": 2, "return_trip": False}

    distance_km = ctx["total_km"]
    if params["return_trip"]:
        distance_km *= 2

    # Use toll from trip_context (already calculated)
    toll = ctx.get("toll", {}).get("amount", 0) or 0
    if params["return_trip"]:
        toll *= 2

    # Calculate
    fuel_cost  = round((distance_km / 15) * 106)   # 15kmpl, ₹106/litre
    food_cost  = round(params["people"] * 400 * (params["nights"] + 1))
    hotel_cost = round(params["nights"] * 1500)
    total      = fuel_cost + food_cost + hotel_cost + toll

    text = (
        f"Budget estimate: {ctx['origin'].title()} → {ctx['destination'].title()}\n"
        f"({distance_km} km, {params['people']} people, {params['nights']} night(s))\n\n"
        f"• Fuel:  ₹{fuel_cost:,}\n"
        f"• Toll:  ₹{toll:,}\n"
        f"• Food:  ₹{food_cost:,}\n"
        f"• Hotel: ₹{hotel_cost:,}\n"
        f"• Total: ₹{total:,}"
    )
    return self.make_response(text, data={"budget": {...}})
```

---

## Task 7 — Update the chat UI (templates/chat.html)

The current UI is a plain chat interface. Add a route card that renders
`trip_context` visually when a trip is planned.

**Add to chat.html:**

```html
<!-- Show trip card if trip_context exists in last response -->
{% if turn.data and turn.data.trip_context %}
<div class="trip-card">
  <div class="trip-header">
    {{ turn.data.trip_context.origin|title }}
    → {{ turn.data.trip_context.destination|title }}
  </div>
  <div class="trip-meta">
    📍 {{ turn.data.trip_context.total_km }} km  ·
    ⏱ {{ turn.data.trip_context.total_eta_min // 60 }}h
       {{ turn.data.trip_context.total_eta_min % 60 }}m
    {% if turn.data.trip_context.toll %}
    · 🪙 ₹{{ turn.data.trip_context.toll.amount }}
    {% endif %}
  </div>
  <div class="checkpoints">
    {% for cp in turn.data.trip_context.checkpoints %}
    <div class="checkpoint">
      <span class="km">{{ cp.km_from_start|int }} km</span>
      <span class="name">{{ cp.name|title }}</span>
      {% if cp.weather %}
      <span class="weather">{{ cp.weather.temp_c }}°C</span>
      {% endif %}
      {% if cp.note %}
      <span class="note">{{ cp.note }}</span>
      {% endif %}
    </div>
    {% endfor %}
  </div>
</div>
{% endif %}
```

Also add a Leaflet map that draws the route when geometry is available:
```javascript
// In the script block
{% if turn.data and turn.data.trip_context and turn.data.trip_context.geometry %}
const coords = {{ turn.data.trip_context.geometry | tojson }};
// Draw polyline on Leaflet map
// Add checkpoint markers
{% endif %}
```

---

## Task 8 — End-to-end test

After all tasks are done, test this exact conversation flow:

```
User: "Delhi to Manali"
Expected: Full trip briefing with 6-8 checkpoints, correct ~10h ETA,
          toll shown, seasonal warnings for current month

User: "what's the weather like?"
Expected: Weather at each checkpoint, natural language summary
          "Clear until Chandigarh, rain from Mandi onwards"

User: "where should I stop for food?"
Expected: Dhabas along the route, one per ~80km segment

User: "how much will it cost? 2 people, 2 nights"
Expected: Budget breakdown using trip_context distance + toll

User: "hotels in Manali"
Expected: Hotel list in Manali specifically
```

All of these should work in sequence, each one building on the same
`session["trip_context"]` set by the first query.

---

## Do not touch

- `tools/polyline.py` — fully tested, pure maths, no changes needed
- `tools/geocoder.py` — fully tested, only change is the import (Task 1)
- `agents/base_agent.py` — foundation, stable
- `agents/router.py` — 3-layer routing works correctly
- `agents/__init__.py` — only add new agents here

---

## Environment variables (.env)

```
LLM_ENDPOINT=http://localhost:11434
LLM_MODEL=qwen2.5
GOOGLE_MAPS_KEY=your_key_here
SESSION_TTL=1800
```

Remove `ORS_KEY` after Task 1 is complete.

---

## Running the project

```bash
# Terminal 1
ollama pull qwen2.5
ollama serve

# Terminal 2
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Add GOOGLE_MAPS_KEY to .env

python3 test_route_agent.py   # verify before starting server
python3 main.py                # start server
# Open http://localhost:8000
```
