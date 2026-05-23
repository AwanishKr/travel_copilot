# Corridor Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a corridor/food agent that enriches each highway segment in a planned trip with famous rest stops, dhabas, and fuel points — searched from the web, summarised by LLM.

**Architecture:** `tools/corridor.py` does the web search (DuckDuckGo HTML → httpx → BeautifulSoup → LLM extraction). `agents/corridor_agent.py` wraps it with trip-mode and standalone-mode like the existing `weather_agent.py`. The route agent fires corridor + weather in parallel after building `trip_context`, then combines everything into one LLM narrative.

**Tech Stack:** Python, httpx (already installed), beautifulsoup4 (new), DuckDuckGo HTML search (no key needed), local Ollama LLM via `call_llm()`.

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `backend/tools/corridor.py` | DuckDuckGo search → page fetch → LLM extraction → stop list |
| Create | `backend/agents/corridor_agent.py` | Trip mode + standalone mode over corridor tool |
| Modify | `backend/agents/route_agent.py` | Parallel handoff + combined narrative |
| Modify | `requirements.txt` | Add beautifulsoup4 |
| Create | `tests/test_corridor_tool.py` | Unit tests for corridor tool |
| Create | `tests/test_corridor_agent.py` | Unit tests for corridor agent |

---

## Task 1: Add beautifulsoup4 to requirements

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add dependency**

Open `requirements.txt` and add:
```
fastapi>=0.111.0
uvicorn[standard]>=0.29.0
jinja2>=3.1.4
httpx>=0.27.0
python-multipart>=0.0.9
beautifulsoup4>=4.12.0
```

- [ ] **Step 2: Install it**

```bash
cd /Users/k2awanish/personal_work/travel_agent
source .venv/bin/activate
pip install beautifulsoup4
```

Expected: `Successfully installed beautifulsoup4-4.x.x`

- [ ] **Step 3: Commit**

```bash
git add requirements.txt
git commit -m "deps: add beautifulsoup4 for corridor web scraping"
```

---

## Task 2: Build `tools/corridor.py`

**Files:**
- Create: `backend/tools/corridor.py`
- Create: `tests/test_corridor_tool.py`

### 2a — Write failing tests first

- [ ] **Step 1: Write the tests**

Create `tests/test_corridor_tool.py`:

```python
"""
tests/test_corridor_tool.py
Tests for the corridor search tool.
Run from project root: python3 -m pytest tests/test_corridor_tool.py -v
"""
import sys, os, asyncio, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

import pytest
from unittest.mock import AsyncMock, patch, MagicMock


# ── helpers ───────────────────────────────────────────────────────────────────

def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ── parse_stops ───────────────────────────────────────────────────────────────

def test_parse_stops_valid_json():
    from tools.corridor import _parse_stops
    raw = '[{"name":"Murthal","type":"dhaba","km_approx":55,"note":"Famous paranthas"}]'
    result = _parse_stops(raw)
    assert len(result) == 1
    assert result[0]["name"] == "Murthal"
    assert result[0]["type"] == "dhaba"


def test_parse_stops_extracts_json_from_prose():
    from tools.corridor import _parse_stops
    raw = 'Here are the stops: [{"name":"Panipat","type":"fuel","km_approx":90,"note":"Fuel stop"}] Done.'
    result = _parse_stops(raw)
    assert result[0]["name"] == "Panipat"


def test_parse_stops_returns_empty_on_garbage():
    from tools.corridor import _parse_stops
    assert _parse_stops("no json here at all") == []


def test_parse_stops_caps_at_five():
    from tools.corridor import _parse_stops
    stops = [{"name": f"Stop{i}", "type": "dhaba", "km_approx": i*10, "note": ""} for i in range(10)]
    raw = json.dumps(stops)
    result = _parse_stops(raw)
    assert len(result) <= 5


# ── build_search_query ────────────────────────────────────────────────────────

def test_build_search_query_contains_corridor():
    from tools.corridor import _build_search_query
    q = _build_search_query("Delhi Dehradun Expressway")
    assert "Delhi Dehradun Expressway" in q
    assert "rest" in q.lower() or "dhaba" in q.lower() or "food" in q.lower()


# ── search_stops (integration-style with mocks) ───────────────────────────────

def test_search_stops_returns_list():
    """search_stops always returns a list, even on total failure."""
    from tools.corridor import search_stops

    with patch("tools.corridor._fetch_ddg_links", new_callable=AsyncMock) as mock_links, \
         patch("tools.corridor._fetch_page_text", new_callable=AsyncMock) as mock_page, \
         patch("tools.corridor._llm_extract_stops", new_callable=AsyncMock) as mock_llm:

        mock_links.return_value = ["http://example.com/1"]
        mock_page.return_value = "Murthal is a famous dhaba stop 55km from Delhi."
        mock_llm.return_value = [{"name": "Murthal", "type": "dhaba", "km_approx": 55, "note": "Famous paranthas"}]

        result = run(search_stops("Delhi Dehradun Expressway", 9.9, 92.2))
        assert isinstance(result, list)
        assert result[0]["name"] == "Murthal"


def test_search_stops_returns_empty_list_on_failure():
    from tools.corridor import search_stops

    with patch("tools.corridor._fetch_ddg_links", new_callable=AsyncMock) as mock_links:
        mock_links.side_effect = Exception("Network error")
        result = run(search_stops("Some Highway", 0, 100))
        assert result == []
```

- [ ] **Step 2: Run tests — confirm they fail**

```bash
cd /Users/k2awanish/personal_work/travel_agent
python3 -m pytest tests/test_corridor_tool.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError: No module named 'tools.corridor'`

### 2b — Implement `tools/corridor.py`

- [ ] **Step 3: Create the file**

Create `backend/tools/corridor.py`:

```python
"""
tools/corridor.py
-----------------
Web search tool for highway rest stops and food places.

Pipeline per corridor:
  DuckDuckGo HTML search
      → top 3 URLs
      → fetch each page via httpx
      → extract <p> text with BeautifulSoup
      → LLM condenses into structured stop list
      → fallback: LLM-only if fetch fails
"""

import re
import json
import asyncio
import httpx
from bs4 import BeautifulSoup

from config import LLM_ENDPOINT, LLM_MODEL

_TIMEOUT      = httpx.Timeout(5.0, connect=3.0)
_MAX_LINKS    = 3
_MAX_TEXT     = 2500   # chars of page text passed to LLM
_MAX_STOPS    = 5

_DDG_URL      = "https://html.duckduckgo.com/html/"
_HEADERS      = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; travel-copilot/1.0; "
        "+https://github.com/your-repo)"
    )
}


# ── Public API ────────────────────────────────────────────────────────────────

async def search_stops(
    corridor_name: str,
    km_start: float,
    km_end: float,
) -> list[dict]:
    """
    Search the web for rest stops on a named highway corridor.

    Returns list of dicts:
        {"name": str, "type": str, "km_approx": int, "note": str}

    type is one of: dhaba | fuel | rest_area | town

    Returns [] on any failure — never raises.
    """
    try:
        query = _build_search_query(corridor_name)
        links = await _fetch_ddg_links(query)

        texts = await asyncio.gather(*[
            _fetch_page_text(link) for link in links[:_MAX_LINKS]
        ])
        combined = "\n\n".join(t for t in texts if t)[:_MAX_TEXT]

        if combined:
            return await _llm_extract_stops(corridor_name, combined)

        # fallback: ask LLM from its own knowledge
        return await _llm_fallback_stops(corridor_name, km_start, km_end)

    except Exception as exc:
        print(f"[corridor] search_stops failed for '{corridor_name}': {exc}")
        return []


# ── Search helpers ────────────────────────────────────────────────────────────

def _build_search_query(corridor_name: str) -> str:
    return f"best rest stops dhabas food fuel {corridor_name} highway India travellers"


async def _fetch_ddg_links(query: str) -> list[str]:
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True) as client:
        resp = await client.get(_DDG_URL, params={"q": query, "kl": "in-en"})
        resp.raise_for_status()

    soup  = BeautifulSoup(resp.text, "html.parser")
    links = []
    for a in soup.select("a.result__a"):
        href = a.get("href", "")
        if href.startswith("http") and "duckduckgo.com" not in href:
            links.append(href)
        if len(links) >= _MAX_LINKS:
            break
    return links


async def _fetch_page_text(url: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        paragraphs = soup.find_all("p")
        text = " ".join(p.get_text(" ", strip=True) for p in paragraphs)
        return text[:_MAX_TEXT]
    except Exception:
        return ""


# ── LLM extraction ────────────────────────────────────────────────────────────

async def _llm_extract_stops(corridor_name: str, web_text: str) -> list[dict]:
    prompt = f"""You are extracting highway rest stop information from web content.
Highway: {corridor_name}

Return ONLY a JSON array. Each item must have exactly these fields:
  "name"      : place name (string)
  "type"      : one of dhaba | fuel | rest_area | town
  "km_approx" : approximate km from the start of the trip (integer, 0 if unknown)
  "note"      : one short sentence about why it matters (string)

Rules:
- Maximum {_MAX_STOPS} stops
- Only include stops clearly on or near {corridor_name}
- If nothing useful is found, return []
- Return ONLY the JSON array, no explanation

Web content:
{web_text}"""

    raw = await _call_llm(prompt)
    return _parse_stops(raw)


async def _llm_fallback_stops(corridor_name: str, km_start: float, km_end: float) -> list[dict]:
    prompt = f"""List the most famous rest stops, dhabas, and fuel points on {corridor_name} in India.
The segment runs from approximately {km_start:.0f} km to {km_end:.0f} km from the trip start.

Return ONLY a JSON array. Each item:
  "name"      : place name (string)
  "type"      : one of dhaba | fuel | rest_area | town
  "km_approx" : approximate km from trip start (integer)
  "note"      : one short sentence

Maximum {_MAX_STOPS} stops. If you don't know, return []."""

    raw = await _call_llm(prompt)
    return _parse_stops(raw)


# ── JSON parsing ──────────────────────────────────────────────────────────────

def _parse_stops(raw: str) -> list[dict]:
    """Extract a JSON array from LLM output. Returns [] on any parse failure."""
    try:
        # strip markdown fences
        raw = re.sub(r"```(?:json)?|```", "", raw).strip()
        # find first [ ... ] block
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if not match:
            return []
        stops = json.loads(match.group())
        if not isinstance(stops, list):
            return []
        # normalise and cap
        result = []
        for s in stops[:_MAX_STOPS]:
            if not isinstance(s, dict) or not s.get("name"):
                continue
            result.append({
                "name":      str(s.get("name", "")).strip(),
                "type":      str(s.get("type", "dhaba")).strip(),
                "km_approx": int(s.get("km_approx", 0)),
                "note":      str(s.get("note", "")).strip(),
            })
        return result
    except Exception:
        return []


# ── LLM caller ────────────────────────────────────────────────────────────────

async def _call_llm(prompt: str) -> str:
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        resp = await client.post(
            f"{LLM_ENDPOINT}/api/generate",
            json={"model": LLM_MODEL, "prompt": prompt, "stream": False},
        )
        resp.raise_for_status()
        return resp.json().get("response", "").strip()
```

- [ ] **Step 4: Run the tests — confirm they pass**

```bash
python3 -m pytest tests/test_corridor_tool.py -v
```

Expected:
```
test_parse_stops_valid_json PASSED
test_parse_stops_extracts_json_from_prose PASSED
test_parse_stops_returns_empty_on_garbage PASSED
test_parse_stops_caps_at_five PASSED
test_build_search_query_contains_corridor PASSED
test_search_stops_returns_list PASSED
test_search_stops_returns_empty_list_on_failure PASSED
```

- [ ] **Step 5: Commit**

```bash
git add backend/tools/corridor.py tests/test_corridor_tool.py
git commit -m "feat: add corridor search tool (DuckDuckGo + BeautifulSoup + LLM)"
```

---

## Task 3: Build `agents/corridor_agent.py`

**Files:**
- Create: `backend/agents/corridor_agent.py`
- Create: `tests/test_corridor_agent.py`

### 3a — Write failing tests

- [ ] **Step 1: Write the tests**

Create `tests/test_corridor_agent.py`:

```python
"""
tests/test_corridor_agent.py
Tests for the corridor agent (trip mode + standalone mode).
Run from project root: python3 -m pytest tests/test_corridor_agent.py -v
"""
import sys, os, asyncio
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

import pytest
from unittest.mock import AsyncMock, patch


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ── Trip mode ─────────────────────────────────────────────────────────────────

def test_trip_mode_writes_corridor_stops_to_context():
    from agents.corridor_agent import CorridorAgent
    agent = CorridorAgent()

    session = {
        "trip_context": {
            "origin": "delhi", "destination": "manali",
            "major_corridors": [
                {"name": "Delhi Dehradun Expressway", "km_start": 9.9, "km_end": 92.2, "length_km": 82.3}
            ],
            "major_cities": [],
        }
    }

    fake_stops = [{"name": "Murthal", "type": "dhaba", "km_approx": 55, "note": "Famous paranthas"}]

    with patch("agents.corridor_agent.search_stops", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = fake_stops
        result = run(agent.handle("suggest stops", session))

    assert result["type"] == "response"
    corridor_stops = session["trip_context"].get("corridor_stops", [])
    assert len(corridor_stops) == 1
    assert corridor_stops[0]["corridor"] == "Delhi Dehradun Expressway"
    assert corridor_stops[0]["stops"] == fake_stops


def test_trip_mode_returns_response_with_stop_names():
    from agents.corridor_agent import CorridorAgent
    agent = CorridorAgent()

    session = {
        "trip_context": {
            "origin": "delhi", "destination": "manali",
            "major_corridors": [
                {"name": "Grand Trunk Road", "km_start": 152.6, "km_end": 235.9, "length_km": 83.2}
            ],
            "major_cities": [],
        }
    }

    fake_stops = [
        {"name": "Karnal", "type": "town", "km_approx": 160, "note": "ATM and fuel"},
        {"name": "Ambala Dhaba", "type": "dhaba", "km_approx": 200, "note": "Good paranthas"},
    ]

    with patch("agents.corridor_agent.search_stops", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = fake_stops
        result = run(agent.handle("food stops", session))

    assert "Karnal" in result["text"] or "Grand Trunk Road" in result["text"]


def test_trip_mode_handles_empty_corridors():
    from agents.corridor_agent import CorridorAgent
    agent = CorridorAgent()

    session = {"trip_context": {"origin": "delhi", "destination": "manali", "major_corridors": [], "major_cities": []}}
    result = run(agent.handle("stops", session))
    assert result["type"] in ("response", "error")


# ── Standalone mode ───────────────────────────────────────────────────────────

def test_standalone_mode_no_trip_context():
    from agents.corridor_agent import CorridorAgent
    agent = CorridorAgent()

    fake_stops = [{"name": "Murthal", "type": "dhaba", "km_approx": 55, "note": "Famous paranthas"}]

    with patch("agents.corridor_agent.search_stops", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = fake_stops
        result = run(agent.handle("rest stops on Delhi Dehradun Expressway", {}))

    assert result["type"] == "response"
    assert "Murthal" in result["text"]


def test_standalone_mode_no_highway_found_returns_clarify():
    from agents.corridor_agent import CorridorAgent
    agent = CorridorAgent()

    result = run(agent.handle("what should I eat today", {}))
    assert result["type"] == "clarify"
```

- [ ] **Step 2: Run — confirm they fail**

```bash
python3 -m pytest tests/test_corridor_agent.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'agents.corridor_agent'`

### 3b — Implement the agent

- [ ] **Step 3: Create `backend/agents/corridor_agent.py`**

```python
"""
agents/corridor_agent.py
------------------------
Corridor agent — suggests rest stops and food places along highway segments.

Two modes:
  Trip mode   : trip_context exists → enrich each corridor via web search
  Standalone  : user asks about a specific highway directly
"""

import re
import asyncio
from agents.base_agent import BaseAgent
from tools.corridor import search_stops

_HIGHWAY_KEYWORDS = [
    "expressway", "highway", "national highway", "nh", "sh",
    "grand trunk", "gt road", "road", "route",
]


class CorridorAgent(BaseAgent):
    name = "corridor"
    description = (
        "Suggests rest stops, dhabas, and fuel points along highway segments "
        "of a planned trip or any named Indian highway."
    )
    keywords = [
        "stop", "stops", "food", "dhaba", "eat", "restaurant", "fuel",
        "petrol", "rest", "break", "highway", "expressway", "along the way",
        "where to eat", "kahan khana", "rest area", "chai", "parantha",
    ]

    async def handle(self, query: str, session: dict) -> dict:
        if session.get("trip_context"):
            return await self._enrich_trip_stops(session)
        return await self._standalone_stops(query)

    # ── Trip mode ─────────────────────────────────────────────────────────────

    async def _enrich_trip_stops(self, session: dict) -> dict:
        ctx        = session["trip_context"]
        corridors  = ctx.get("major_corridors", [])

        if not corridors:
            ctx["corridor_stops"] = []
            return self.make_response("No major highway corridors found for this trip.")

        # Search all corridors concurrently
        results = await asyncio.gather(*[
            search_stops(c["name"], c["km_start"], c["km_end"])
            for c in corridors
        ])

        corridor_stops = [
            {"corridor": c["name"], "stops": stops}
            for c, stops in zip(corridors, results)
        ]
        ctx["corridor_stops"] = corridor_stops

        return self.make_response(
            _format_corridor_stops(corridor_stops),
            data={"corridor_stops": corridor_stops},
        )

    # ── Standalone mode ───────────────────────────────────────────────────────

    async def _standalone_stops(self, query: str) -> dict:
        highway = _extract_highway(query)
        if not highway:
            return self.make_clarify(
                "Which highway are you asking about? "
                "E.g. 'stops on Delhi Dehradun Expressway' or 'dhabas on GT Road'."
            )

        stops = await search_stops(highway, 0, 9999)
        if not stops:
            return self.make_response(
                f"Couldn't find specific stop information for {highway}. "
                "Try asking after planning a trip — e.g. 'Delhi to Manali'."
            )

        lines = [f"Stops on {highway}:\n"]
        for s in stops:
            lines.append(f"  {_type_icon(s['type'])} {s['name']}  — {s['note']}")
        return self.make_response("\n".join(lines))


# ── Formatting ────────────────────────────────────────────────────────────────

def _format_corridor_stops(corridor_stops: list[dict]) -> str:
    if not any(cs["stops"] for cs in corridor_stops):
        return "No specific stop information found for the highways on this route."

    lines = []
    for cs in corridor_stops:
        if not cs["stops"]:
            continue
        lines.append(f"\n{cs['corridor']}:")
        for s in cs["stops"]:
            lines.append(f"  {_type_icon(s['type'])} {s['name']}  — {s['note']}")
    return "\n".join(lines).strip()


def _type_icon(stop_type: str) -> str:
    return {"dhaba": "🍽", "fuel": "⛽", "rest_area": "🛖", "town": "🏙"}.get(stop_type, "📍")


# ── Highway extraction ────────────────────────────────────────────────────────

def _extract_highway(query: str) -> str | None:
    """
    Extract a highway name from a freeform query.
    Looks for known highway keywords and returns the surrounding phrase.
    """
    q = query.strip()
    # Match phrases like "Delhi Dehradun Expressway" or "GT Road" or "NH 44"
    pattern = r"(?:[\w\s]+(?:expressway|highway|gt road|grand trunk road|nh[\s\-]?\d+|sh[\s\-]?\d+)[\w\s]*)"
    match = re.search(pattern, q, re.IGNORECASE)
    if match:
        return match.group().strip()

    # Fallback: if any highway keyword is present, return the whole query as the search term
    if any(kw in q.lower() for kw in _HIGHWAY_KEYWORDS):
        return q
    return None
```

- [ ] **Step 4: Run the tests**

```bash
python3 -m pytest tests/test_corridor_agent.py -v
```

Expected: all 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/agents/corridor_agent.py tests/test_corridor_agent.py
git commit -m "feat: add corridor agent with trip mode and standalone mode"
```

---

## Task 4: Wire corridor agent into router

**Files:**
- Modify: `backend/agents/router.py`

- [ ] **Step 1: Check current router structure**

```bash
cat backend/agents/router.py
```

- [ ] **Step 2: Register CorridorAgent in the router**

Find where agents are imported and instantiated (look for `WeatherAgent`, `RouteAgent` etc.) and add `CorridorAgent` in the same pattern. Example — if the router has a list like:

```python
from agents.weather_agent import WeatherAgent
from agents.route_agent   import RouteAgent
# ... other agents
```

Add:
```python
from agents.corridor_agent import CorridorAgent
```

And wherever agents are listed/instantiated, add `CorridorAgent()` in the same place.

- [ ] **Step 3: Verify import works**

```bash
cd backend && python3 -c "from agents.router import Router; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/agents/router.py
git commit -m "feat: register corridor agent in router"
```

---

## Task 5: Update route agent for parallel handoff

**Files:**
- Modify: `backend/agents/route_agent.py`

The current `handle()` flow in route agent is:
1. Extract cities
2. Geocode
3. get_directions
4. build_travel_context
5. generate_summary (LLM)
6. store in session

We need to change it to:
1. Extract cities
2. Geocode
3. get_directions
4. build_travel_context
5. **Store in session** ← moved up so agents can read it
6. **Fire corridor_agent + weather_agent in parallel** ← new
7. generate_summary using enriched context (LLM)
8. Return combined response

- [ ] **Step 1: Add import for CorridorAgent and WeatherAgent**

At the top of `backend/agents/route_agent.py`, add:

```python
from agents.corridor_agent import CorridorAgent
from agents.weather_agent  import WeatherAgent

_corridor_agent = CorridorAgent()
_weather_agent  = WeatherAgent()
```

- [ ] **Step 2: Replace the `handle()` body**

Find the current `handle()` method and replace it with:

```python
async def handle(self, query: str, session: dict) -> dict:

    # Step 1 — Extract origin / destination from natural language
    parsed      = await self._extract_route(query, session)
    origin      = parsed.get("origin")
    destination = parsed.get("destination")
    via         = parsed.get("via", [])

    if not origin or not destination:
        if origin:
            session["partial_origin"] = origin
        return self.make_clarify(self._clarify_message(origin, destination))

    # Step 2 — Geocode
    coords = await self._geocode_all([origin] + via + [destination])
    if len(coords) < 2:
        return self.make_error(
            f"Could not locate '{origin}' or '{destination}'. "
            "Try using a major city name."
        )

    origin_coords = coords[0]
    dest_coords   = coords[-1]
    via_coords    = coords[1:-1]

    # Step 3 — Tool: get_directions
    raw = await self._tool_get_directions(origin_coords, dest_coords, via_coords)

    # Step 4 — Tool: build_travel_context
    travel_context = self._tool_build_travel_context(
        raw, origin, destination, via, origin_coords, dest_coords
    )

    # Step 5 — Store in session so corridor + weather agents can read it
    session["trip_context"] = travel_context
    session["last_cities"]  = [origin] + via + [destination]

    # Step 6 — Enrich in parallel: corridor stops + weather
    await asyncio.gather(
        _corridor_agent.handle("stops along route", session),
        _weather_agent.handle("weather along route", session),
    )

    # Step 7 — Generate combined narrative
    summary = await self._generate_summary(session["trip_context"])

    return self.make_response(summary, data={"trip_context": session["trip_context"]})
```

- [ ] **Step 3: Update `_generate_summary` to include corridor stops**

Find `_generate_summary` and update the prompt to include stop data. Replace the existing method with:

```python
async def _generate_summary(self, ctx: dict) -> str:
    summary     = ctx.get("trip_summary", {})
    origin      = summary.get("origin", ctx.get("origin", "")).title()
    destination = summary.get("destination", ctx.get("destination", "")).title()
    total_km    = summary.get("total_km") or ctx.get("total_km", 0)
    duration_hr = summary.get("duration_hr") or round((ctx.get("total_eta_min", 0)) / 60, 1)
    has_toll    = summary.get("has_toll", False)

    corridors      = ctx.get("major_corridors", [])
    cities         = ctx.get("major_cities", [])
    corridor_stops = ctx.get("corridor_stops", [])

    corridor_names = ", ".join(c["name"] for c in corridors) if corridors else "highway"
    cities_desc    = ", ".join(c["name"].title() for c in cities) if cities else ""

    stops_desc = ""
    for cs in corridor_stops:
        if cs["stops"]:
            stops_desc += f"\n{cs['corridor']}:\n"
            for s in cs["stops"]:
                stops_desc += f"  - {s['name']} ({s['type']}): {s['note']}\n"

    # Build weather summary from checkpoints
    weather_lines = []
    for cp in ctx.get("checkpoints", []):
        w = cp.get("weather")
        if w:
            weather_lines.append(f"  {cp['name'].title()}: {w.get('condition','')}, {w.get('temp_c','')}°C")
    weather_desc = "\n".join(weather_lines)

    prompt = f"""You are an experienced Indian long-distance road trip co-driver giving a pre-trip briefing.

Route: {origin} to {destination}
Distance: {total_km} km  |  Estimated drive time: {duration_hr} hrs
Main highways: {corridor_names}
{"Cities along the way: " + cities_desc if cities_desc else ""}
{"Note: this route has toll roads." if has_toll else ""}

{"Recommended stops along the way:" + stops_desc if stops_desc else ""}

{"Weather at key cities:" + chr(10) + weather_desc if weather_desc else ""}

Write a natural pre-trip briefing in 3-5 short paragraphs. Tone: calm, knowledgeable, practical — like a friend who has driven this route many times.
- Mention the highways and what the drive is like
- Name the major cities the driver passes through
- Call out 2-3 notable stops if available
- Mention any weather worth noting
Do NOT use bullet points or headers. Plain paragraphs only."""

    try:
        return await self.call_llm(prompt)
    except Exception:
        return self._static_summary(ctx)
```

- [ ] **Step 4: Update `_static_summary` to include stops**

Replace `_static_summary`:

```python
def _static_summary(self, ctx: dict) -> str:
    summary        = ctx.get("trip_summary", {})
    origin         = summary.get("origin", ctx.get("origin", "")).title()
    destination    = summary.get("destination", ctx.get("destination", "")).title()
    total_km       = summary.get("total_km") or ctx.get("total_km", 0)
    duration_hr    = summary.get("duration_hr", 0)
    corridors      = ctx.get("major_corridors", [])
    cities         = ctx.get("major_cities", [])
    corridor_stops = ctx.get("corridor_stops", [])
    has_toll       = summary.get("has_toll", False)

    lines = [f"Your trip from {origin} to {destination} — {total_km} km, ~{duration_hr} hrs."]

    if corridors:
        lines.append("Route: " + " → ".join(c["name"] for c in corridors))

    if cities:
        names = ", ".join(
            c["name"].title() for c in cities
            if c["name"] not in (origin.lower(), destination.lower())
        )
        if names:
            lines.append(f"Passing through: {names}")

    for cs in corridor_stops:
        if cs["stops"]:
            lines.append(f"\nStops on {cs['corridor']}:")
            for s in cs["stops"]:
                lines.append(f"  • {s['name']} ({s['type']}) — {s['note']}")

    if has_toll:
        lines.append("Note: this route has toll roads.")

    return "\n".join(lines)
```

- [ ] **Step 5: Verify the file imports cleanly**

```bash
cd /Users/k2awanish/personal_work/travel_agent/backend && python3 -c "
from agents.route_agent import RouteAgent
print('RouteAgent imports OK')
"
```

Expected: `RouteAgent imports OK`

- [ ] **Step 6: Commit**

```bash
git add backend/agents/route_agent.py
git commit -m "feat: route agent fires corridor + weather in parallel, combines into one narrative"
```

---

## Task 6: Smoke test end-to-end

- [ ] **Step 1: Run all tests**

```bash
cd /Users/k2awanish/personal_work/travel_agent
python3 -m pytest tests/test_corridor_tool.py tests/test_corridor_agent.py -v
```

Expected: all tests pass.

- [ ] **Step 2: Quick manual smoke test against saved raw route data**

```bash
cd /Users/k2awanish/personal_work/travel_agent/backend && python3 -c "
import asyncio, json, sys
sys.path.insert(0, '.')
from tools.corridor import search_stops

async def main():
    stops = await search_stops('Delhi Dehradun Expressway', 9.9, 92.2)
    print(json.dumps(stops, indent=2))

asyncio.run(main())
"
```

Expected: JSON array with 1-5 stop objects. If LLM is offline, expect `[]`.

- [ ] **Step 3: Final commit if any cleanup needed**

```bash
git add -p   # review any stray changes
git commit -m "chore: corridor agent smoke test cleanup"
```

---

## Self-Review Checklist

- [x] `search_stops` always returns `list`, never raises → caught in try/except
- [x] `_parse_stops` caps at `_MAX_STOPS = 5` → tested
- [x] Corridor agent trip mode writes to `session["trip_context"]["corridor_stops"]` → tested
- [x] Route agent stores `trip_context` in session BEFORE firing parallel agents → step 5 before step 6
- [x] `_generate_summary` reads `corridor_stops` key → matches what corridor agent writes
- [x] `_static_summary` updated to match → no old `toll`/`seasonal_warnings` refs
- [x] Router registers `CorridorAgent` → task 4
- [x] No new required env vars — DuckDuckGo needs no key
