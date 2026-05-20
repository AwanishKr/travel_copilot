"""
agents/route_agent.py
----------------------
Route agent — foundation of the trip co-pilot.

Workflow:
  1. Extract origin + destination from natural language (LLM or regex)
  2. Geocode cities to coordinates
  3. Tool: get_directions  → calls Mappls API, returns raw route JSON
  4. Tool: build_travel_context → applies deterministic filter, returns travel_context
  5. Generate a natural language pre-trip narrative (LLM)
  6. Store travel_context in session for downstream agents
"""

import re
import asyncio
import json

from agents.base_agent import BaseAgent
from tools.geocoder import extract_cities, geocode, geocode_sync
from tools.mappls import get_directions as mappls_get_directions
from tools.polyline import haversine_km
from tools.route_filter import filter_route
from agents.corridor_agent import CorridorAgent
from agents.weather_agent  import WeatherAgent

_corridor_agent = CorridorAgent()
_weather_agent  = WeatherAgent()


class RouteAgent(BaseAgent):
    name = "route"
    description = (
        "Plans road trips between Indian cities. Gives distance, drive time, "
        "checkpoints, toll cost, and a co-driver style pre-trip summary."
    )
    keywords = [
        "route", "distance", "how far", "kitna dur", "drive", "driving",
        "how long", "kitna time", "time to reach", "km", "kilometers",
        "highway", "road", "rasta", "pahunchna", "travel time", "trip",
        "toll", "expressway", "via", "through", "fastest way", "plan",
        "journey", "safar", "reach", "jana hai", "jaana",
    ]

    # ── Entry point ───────────────────────────────────────────────────────────

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

        # Step 7 — Generate combined narrative from enriched context
        summary = await self._generate_summary(session["trip_context"])

        return self.make_response(summary, data={"trip_context": session["trip_context"]})

    # ── Tool 1: get_directions ────────────────────────────────────────────────

    async def _tool_get_directions(
        self,
        origin_coords: tuple,
        dest_coords: tuple,
        via_coords: list[tuple],
    ) -> dict | None:
        """
        Calls the Mappls Directions API and returns raw route JSON.
        No processing — just the API response.
        """
        return await mappls_get_directions(
            origin_coords,
            dest_coords,
            via=via_coords if via_coords else None,
            alternatives=False,
            steps=True,
        )

    # ── Tool 2: build_travel_context ─────────────────────────────────────────

    def _tool_build_travel_context(
        self,
        raw: dict | None,
        origin: str,
        destination: str,
        via: list[str],
        origin_coords: tuple,
        dest_coords: tuple,
    ) -> dict:
        """
        Applies the deterministic route filter to raw Mappls JSON
        and returns a structured travel_context.
        No LLM — pure logic on road names and coordinates.
        """
        if not raw or not raw.get("routes"):
            dist_km = round(haversine_km(origin_coords, dest_coords) * 1.3, 1)
            eta_min = round(dist_km)
            return {
                "trip_summary":    {"origin": origin, "destination": destination,
                                    "via": via, "total_km": dist_km,
                                    "duration_hr": round(dist_km / 60, 1),
                                    "total_eta_min": eta_min, "has_toll": False},
                "major_corridors": [],
                "major_cities":    [],
                "origin":          origin,
                "destination":     destination,
                "via":             via,
                "total_km":        dist_km,
                "total_eta_min":   eta_min,
                "geometry":        [],
                "checkpoints":     [],
                "route_source":    "estimated",
                "status":          "planned",
            }

        return filter_route(raw, origin, destination, via=via)

    # ── Natural language summary ──────────────────────────────────────────────

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

    # ── Entity extraction ─────────────────────────────────────────────────────

    async def _extract_route(self, query: str, session: dict) -> dict:
        last = session.get("last_cities", [])
        context_note = f"Previous route context: {last}" if last else ""

        prompt = f"""Extract the travel route from this query.
Return ONLY a JSON object with this exact shape:
{{"origin": "<city lowercase or null>", "destination": "<city lowercase or null>", "via": []}}

Rules:
- Use simple lowercase city names (e.g. "delhi", "manali", "mumbai")
- "via" must be an empty list [] when there are no intermediate stops — never put "null" inside the list
- If origin or destination cannot be determined, use null (not the string "null")
- Resolve aliases: bombay=mumbai, calcutta=kolkata, madras=chennai, benares=varanasi
- "How far is X from Y?" → origin=Y, destination=X
- "X se Y jana hai" (Hindi) → origin=X, destination=Y
- "City1 City2 City3 road trip" → origin=City1, destination=City3, via=[City2]
- The first city mentioned is usually origin, the last is destination
{context_note}

Query: "{query}"

Reply with ONLY the JSON object, nothing else."""

        try:
            raw = await self.call_llm(prompt)
            raw = re.sub(r"```(?:json)?|```", "", raw).strip()
            result      = json.loads(raw)
            origin      = result.get("origin") or None
            destination = result.get("destination") or None
            via         = [v for v in (result.get("via") or [])
                           if isinstance(v, str) and v.lower() not in ("null", "none", "")]
            if isinstance(origin, str) and origin.lower() in ("null", "none"):
                origin = None
            if isinstance(destination, str) and destination.lower() in ("null", "none"):
                destination = None
            return {"origin": origin, "destination": destination, "via": via}
        except Exception as e:
            print(f"[route_agent] LLM extraction failed ({e}), falling back to regex")
            return self._regex_fallback(query, session)

    def _regex_fallback(self, query: str, session: dict) -> dict:
        cities  = extract_cities(query)
        q_lower = query.lower()
        via     = []

        via_match = re.search(r"\bvia\b(.+?)(?:\bto\b|$)", q_lower)
        if via_match:
            via = extract_cities(via_match.group(1))

        main_cities = [c for c in cities if c not in via]

        from_match = re.search(r"\bfrom\s+(\w+(?:\s+\w+)?)", q_lower)
        if from_match and len(main_cities) == 2:
            from_city = next(
                (c for c in main_cities if re.search(rf"\b{re.escape(c)}\b", from_match.group(1))),
                None,
            )
            if from_city and from_city != main_cities[0]:
                main_cities = [from_city] + [c for c in main_cities if c != from_city]

        if len(main_cities) >= 2:
            origin      = main_cities[0]
            destination = main_cities[-1]
            if len(main_cities) > 2:
                via = list(dict.fromkeys(via + main_cities[1:-1]))
        elif len(main_cities) == 1:
            if session.get("partial_origin"):
                origin      = session.pop("partial_origin")
                destination = main_cities[0]
            elif session.get("last_cities"):
                origin      = session["last_cities"][0]
                destination = main_cities[0]
            else:
                origin, destination = main_cities[0], None
        elif session.get("last_cities"):
            prev        = session["last_cities"]
            origin      = prev[0]
            destination = prev[-1]
            via         = prev[1:-1] if len(prev) > 2 else []
        else:
            origin = destination = None

        return {"origin": origin, "destination": destination, "via": via}

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _geocode_all(self, places: list[str]) -> list[tuple]:
        results = await asyncio.gather(*[geocode(p) for p in places])
        return [r for r in results if r is not None]

    def _clarify_message(self, origin, destination) -> str:
        if origin and not destination:
            return f"Got it — starting from {origin.title()}. Where are you headed?"
        if destination and not origin:
            return f"Sure! Where are you starting from to get to {destination.title()}?"
        return (
            "I need your starting point and destination to plan the route. "
            "Try: 'Delhi to Manali' or 'Plan a trip from Delhi to Jaipur via Agra'."
        )
