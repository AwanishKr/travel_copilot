# Corridor Agent Design
_Date: 2026-05-20_

## Goal

Add a food/rest-stop layer to the travel co-pilot. When a trip is planned, the system automatically enriches each highway corridor with famous stops (dhabas, fuel, rest areas) by searching the web — the same way a human would: open DuckDuckGo, read a few links, extract the useful bits.

---

## Context

After the route agent runs, `trip_context` contains:

```python
"major_corridors": [
    {"name": "Delhi Dehradun Expressway", "km_start": 9.9, "km_end": 92.2, "length_km": 82.3},
    {"name": "Grand Trunk Road",          "km_start": 152.6, "km_end": 235.9, "length_km": 83.2},
    ...
]
"major_cities": [
    {"name": "karnal", "km_from_start": 160.0, "coords": [...]},
    ...
]
```

The corridor agent reads these two fields and enriches them with stop data.

---

## Architecture

```
User: "Delhi to Manali"
    └── Route Agent
            ├── builds travel_context
            └── fires in parallel:
                  ├── Corridor Agent  ← new
                  └── Weather Agent   ← existing
            └── LLM combines all three into one response
```

The route agent `await`s both agents concurrently after building `trip_context`, then passes combined context to the LLM for the final narrative.

---

## New Files

### `tools/corridor.py`

The search tool. No agent logic here — pure data fetching and extraction.

**`search_stops(corridor_name, km_start, km_end) → list[dict]`**

Steps:
1. Build query: `f"rest stops food dhabas {corridor_name} highway India"`
2. GET `https://html.duckduckgo.com/html/?q=<query>` via `httpx`
3. Parse result links with `BeautifulSoup`, take top 3
4. For each link: GET the page, extract `<p>` text, truncate to ~2000 chars
5. Pass all extracted text + corridor name to LLM
6. LLM returns a list of stops in structured form
7. Fallback: if fetch fails or LLM returns nothing, return `[]` silently

**Stop schema (minimal):**
```python
{
    "name": "Murthal",
    "type": "dhaba",        # dhaba | fuel | rest_area | town
    "km_approx": 55,        # approximate km from trip start
    "note": "Famous paranthas, open 24hr"
}
```

**LLM prompt contract:**
```
You are extracting rest stop information from web content about {corridor_name}.
Return ONLY a JSON array of stops. Each stop: {"name": str, "type": str, "km_approx": int, "note": str}
Types: dhaba, fuel, rest_area, town. Max 5 stops. If nothing useful found, return [].

Web content:
{extracted_text}
```

---

### `agents/corridor_agent.py`

Thin agent layer over `tools/corridor.py`. Follows the same two-mode pattern as `weather_agent.py`.

**Trip mode** (called by route agent after `trip_context` is set):
- Reads `major_corridors` from `trip_context`
- Calls `search_stops()` for each corridor concurrently via `asyncio.gather`
- Writes results back to `trip_context["corridor_stops"]`
- Returns a formatted text block for inclusion in the route response

**Standalone mode** (user asks directly without a planned trip):
- Parses highway name from query
- Calls `search_stops()` directly
- Returns formatted stops list

**`trip_context` enrichment:**
```python
"corridor_stops": [
    {
        "corridor": "Delhi Dehradun Expressway",
        "stops": [
            {"name": "Murthal", "type": "dhaba", "km_approx": 55, "note": "Famous paranthas, open 24hr"},
            {"name": "Panipat", "type": "fuel",  "km_approx": 90, "note": "Last major fuel before Karnal"},
        ]
    },
    ...
]
```

---

### Route agent change (`agents/route_agent.py`)

After `_tool_build_travel_context()`, fire corridor and weather agents in parallel:

```python
corridor_task = corridor_agent.handle("stops along route", session)
weather_task  = weather_agent.handle("weather along route", session)
corridor_result, weather_result = await asyncio.gather(corridor_task, weather_task)
```

Pass all context to LLM for the final combined narrative.

---

## Data Flow

```
DuckDuckGo HTML search
    → top 3 URLs
    → httpx fetches each page
    → BeautifulSoup extracts <p> text
    → LLM extracts structured stops
    → corridor_agent writes to trip_context["corridor_stops"]
    → route agent LLM combines route + stops + weather into narrative
```

---

## Error Handling

- DuckDuckGo unreachable → skip corridor enrichment, narrative omits stops section
- A link fetch times out (5s timeout per link) → skip that link, use remaining
- LLM returns malformed JSON → catch, return `[]`, log warning
- All three links fail → fallback: LLM generates stops from its own training knowledge for that corridor

---

## Dependencies to Add

```
beautifulsoup4
```

`httpx` is already in the project.

---

## What This Is NOT

- Not real-time. Stops are fetched once when the trip is planned, not as the user drives.
- Not personalised. No dietary preferences, no ratings filtering.
- Not exhaustive. Max 5 stops per corridor — enough for a co-driver briefing.

These are real-time phase concerns.

---

## Success Criteria

- Delhi → Manali query returns at least 2 recognisable stops on the Delhi Dehradun Expressway segment
- Corridor agent works standalone: "stops on GT Road" returns results without a planned trip
- If search fails entirely, route response still works — stops section just absent
- No new required env vars (DuckDuckGo needs no key)
