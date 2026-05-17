"""
agents/route_agent.py
----------------------
The route agent — foundation of the trip co-pilot.

Responsibilities:
  1. Parse origin, destination, via cities from natural language
  2. Geocode all places to coordinates
  3. Call ORS Directions API → route geometry + steps
  4. Decode polyline → coordinates
  5. Use steps to identify natural road-change checkpoints
  6. Ask LLM to enrich each checkpoint with local knowledge
  7. Build trip_context and store in session
  8. Return a clean trip briefing to the user

trip_context shape (stored in session["trip_context"]):
  {
    "origin":       "delhi",
    "destination":  "manali",
    "via":          [],
    "total_km":     572.0,
    "total_eta_min": 640,
    "geometry":     [(lat, lon), ...],   # sampled, ~10-15 points
    "checkpoints": [
      {
        "name":          "panipat",
        "coords":        (29.39, 76.96),
        "km_from_start": 90.0,
        "type":          "fuel_food",
        "note":          "First major stop. Good dhabas on NH-44.",
        "weather":       None,   # filled by weather agent later
        "places":        [],     # filled by places agent later
      },
      ...
    ],
    "route_source": "ors" | "estimated",
    "status":       "planned",
  }
"""

import re
import datetime
import asyncio
import json

from agents.base_agent import BaseAgent
from tools.geocoder import extract_cities, geocode, geocode_sync, CITY_COORDS
from tools.mappls import get_directions
from tools.polyline import decode, sample, steps_to_segments, total_distance_km, haversine_km


# Checkpoint type definitions — used by LLM prompt and UI rendering
CHECKPOINT_TYPES = {
    "fuel_food":        "Fuel & food stop",
    "major_city":       "Major city — ATM, hospital, last highway amenities",
    "gateway":          "Character change — road type or terrain shifts here",
    "mountain_critical":"Mountain zone — weather & road conditions critical",
    "scenic":           "Scenic stop or viewpoint",
    "destination":      "Final destination",
}

# Known seasonal road closures (month → warnings)
SEASONAL_WARNINGS = {
    1:  ["Rohtang Pass closed (Nov–May)", "Leh–Manali highway closed for winter"],
    2:  ["Rohtang Pass closed", "Leh–Manali highway closed"],
    3:  ["Rohtang Pass closed — opening late April/May"],
    4:  ["Rohtang Pass opening soon — verify with HRTC before travelling"],
    5:  ["Rohtang Pass likely open by late May — confirm before departing"],
    6:  ["Monsoon: NH-48 Sohna ghat — landslide risk", "Char Dham — heavy pilgrim traffic"],
    7:  ["Monsoon: avoid Himalayan routes if possible", "Mumbai–Goa coastal highway landslide prone"],
    8:  ["Peak monsoon: landslide risk on all hill routes"],
    9:  ["Post-monsoon: roads reopening, Leh–Manali closing around October"],
    10: ["Rohtang Pass closing soon (Oct–Nov) — last chance"],
    11: ["Rohtang Pass closed for winter", "Leh–Manali highway closed"],
    12: ["Rohtang Pass closed", "Leh–Manali highway closed"],
}

HIMALAYAN_PLACES = {
    "manali", "leh", "shimla", "dharamshala", "mussoorie",
    "nainital", "rishikesh", "haridwar", "dehradun", "mandi",
    "kullu", "bilaspur", "srinagar", "jammu", "ropar",
}

# Toll estimates for major routes (INR, one way)
TOLL_TABLE = {
    frozenset({"delhi", "jaipur"}):     {"amount": 415,  "highway": "NH-48"},
    frozenset({"delhi", "agra"}):       {"amount": 375,  "highway": "Yamuna Expressway"},
    frozenset({"delhi", "chandigarh"}): {"amount": 295,  "highway": "NH-44"},
    frozenset({"delhi", "amritsar"}):   {"amount": 620,  "highway": "NH-44"},
    frozenset({"delhi", "manali"}):     {"amount": 890,  "highway": "NH-44 / NH-3"},
    frozenset({"delhi", "shimla"}):     {"amount": 480,  "highway": "NH-44 / NH-5"},
    frozenset({"delhi", "dehradun"}):   {"amount": 310,  "highway": "NH-58"},
    frozenset({"delhi", "haridwar"}):   {"amount": 220,  "highway": "NH-58"},
    frozenset({"delhi", "mumbai"}):     {"amount": 1650, "highway": "NH-48"},
    frozenset({"mumbai", "pune"}):      {"amount": 310,  "highway": "Mumbai–Pune Expressway"},
    frozenset({"delhi", "lucknow"}):    {"amount": 540,  "highway": "NH-27"},
    frozenset({"jaipur", "udaipur"}):   {"amount": 280,  "highway": "NH-48"},
    frozenset({"jaipur", "jodhpur"}):   {"amount": 190,  "highway": "NH-62"},
    frozenset({"agra", "jaipur"}):      {"amount": 220,  "highway": "NH-21"},
}


class RouteAgent(BaseAgent):
    name = "route"
    description = (
        "Plans road trips between Indian cities. Gives distance, drive time, "
        "checkpoints, toll cost, and a full trip briefing. Handles multi-stop "
        "and via-city routes."
    )
    keywords = [
        "route", "distance", "how far", "kitna dur", "drive", "driving",
        "how long", "kitna time", "time to reach", "km", "kilometers",
        "highway", "road", "rasta", "pahunchna", "travel time", "trip",
        "toll", "expressway", "via", "through", "fastest way", "plan",
        "journey", "safar", "reach", "jana hai", "jaana",
    ]

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    async def handle(self, query: str, session: dict) -> dict:
        parsed = await self._extract_route(query, session)
        origin      = parsed.get("origin")
        destination = parsed.get("destination")
        via         = parsed.get("via", [])

        if not origin or not destination:
            if origin:
                session["partial_origin"] = origin
            return self.make_clarify(self._clarify_message(origin, destination))

        # --- Stage 1: geocode all places ---
        coords = await self._geocode_all([origin] + via + [destination])
        if len(coords) < 2:
            return self.make_error(
                f"Could not locate '{origin}' or '{destination}'. "
                "Try using a major city name."
            )

        origin_coords = coords[0]
        dest_coords   = coords[-1]
        via_coords    = coords[1:-1]

        # --- Stage 2: get route from ORS ---
        ors_result = await get_directions(
            origin_coords,
            dest_coords,
            via=via_coords if via_coords else None,
            alternatives=False,
            steps=True,
        )

        # --- Stage 3: build trip_context ---
        trip_context = await self._build_trip_context(
            origin, destination, via,
            origin_coords, dest_coords,
            ors_result,
        )

        # --- Stage 4: store in session ---
        session["trip_context"]  = trip_context
        session["last_cities"]   = [origin] + via + [destination]
        session["last_route"]    = trip_context

        # --- Stage 5: format and return response ---
        text = self._format_briefing(trip_context)
        return self.make_response(text, data={"trip_context": trip_context})

    # ------------------------------------------------------------------
    # Stage 1: Parse query
    # ------------------------------------------------------------------

    async def _extract_route(self, query: str, session: dict) -> dict:
        """
        Use LLM to extract origin, destination, and via cities
        from natural language. Handles any phrasing including Hindi.

        Falls back to regex extraction if LLM is unavailable.

        Returns: {"origin": str|None, "destination": str|None, "via": []}
        """
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
            result = json.loads(raw)
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
        """
        Regex-based extraction — used when LLM is unavailable.
        Less accurate but always works offline.
        """
        cities  = extract_cities(query)
        q_lower = query.lower()

        via = []
        via_match = re.search(r"\bvia\b(.+?)(?:\bto\b|$)", q_lower)
        if via_match:
            via = extract_cities(via_match.group(1))

        main_cities = [c for c in cities if c not in via]

        # "X from Y" → Y is origin
        from_match = re.search(r"\bfrom\s+(\w+(?:\s+\w+)?)", q_lower)
        if from_match and len(main_cities) == 2:
            from_city = next(
                (c for c in main_cities
                 if re.search(rf"\b{re.escape(c)}\b", from_match.group(1))),
                None
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

    # ------------------------------------------------------------------
    # Stage 2: Geocode
    # ------------------------------------------------------------------

    async def _geocode_all(self, places: list[str]) -> list[tuple[float, float]]:
        """Geocode all places concurrently. Returns only successful results."""
        results = await asyncio.gather(*[geocode(p) for p in places])
        return [r for r in results if r is not None]

    # ------------------------------------------------------------------
    # Stage 3: Build trip_context
    # ------------------------------------------------------------------

    async def _build_trip_context(
        self,
        origin: str,
        destination: str,
        via: list[str],
        origin_coords: tuple,
        dest_coords: tuple,
        ors_result: dict | None,
    ) -> dict:
        """
        Core function — assembles the full trip_context dict.
        """
        all_places = [origin] + via + [destination]
        month      = datetime.datetime.now().month

        context = {
            "origin":        origin,
            "destination":   destination,
            "via":           via,
            "total_km":      None,
            "total_eta_min": None,
            "geometry":      [],
            "checkpoints":   [],
            "toll":          self._get_toll(origin, destination),
            "seasonal_warnings": self._get_seasonal_warnings(all_places, month),
            "route_source":  "estimated",
            "status":        "planned",
        }

        if ors_result and ors_result.get("routes"):
            route     = ors_result["routes"][0]
            context["total_km"]      = round(route["distance_m"] / 1000, 1)
            context["total_eta_min"] = round(route["duration_s"] / 60)
            context["route_source"]  = "mappls"

            # Decode geometry → coordinates (Mappls uses polyline6)
            if route.get("geometry"):
                full_coords = decode(route["geometry"], precision=6)
                sampled = sample(full_coords, every_km=40)
                context["geometry"] = [s["coords"] for s in sampled]

            full_coords = decode(route["geometry"], precision=6) if route.get("geometry") else []
            if full_coords:
                sampled = sample(full_coords, every_km=40)
                context["geometry"] = [s["coords"] for s in sampled]

        else:
            # Mappls unavailable — estimate from haversine
            dist_km = round(haversine_km(origin_coords, dest_coords) * 1.3, 1)
            context["total_km"]      = dist_km
            context["total_eta_min"] = round(dist_km / 60 * 60)
            full_coords = []

        # LLM discovers and enriches stops in one shot
        checkpoints = await self._discover_checkpoints(
            origin, destination, via,
            context["total_km"] or 0,
            full_coords,
        )
        context["checkpoints"] = checkpoints

        return context

    # ------------------------------------------------------------------
    # Checkpoint discovery — LLM names the stops, geometry pins the km
    # ------------------------------------------------------------------

    async def _discover_checkpoints(
        self,
        origin: str,
        destination: str,
        via: list[str],
        total_km: float,
        full_coords: list[tuple],
    ) -> list[dict]:
        """
        Ask the LLM to name all important stops on this route
        (dhabas, fuel, landmarks, cities, gateways) then geocode each one
        and pin it to the route geometry to get km_from_start.

        Falls back to origin + destination only if LLM is unavailable.
        """
        via_str = f" via {', '.join(v.title() for v in via)}" if via else ""

        # Provide known corridor cities as a hint so the small LLM
        # stays on the correct highway and doesn't suggest off-route cities
        corridor = self._corridor_hint(origin, destination, full_coords)
        corridor_note = f"\nKnown stops that are actually on this route (prioritise these): {corridor}" if corridor else ""

        prompt = f"""You are an expert on Indian road trips with deep knowledge of highways, famous dhabas, landmarks, and rest stops.

Route: {origin.title()} → {destination.title()}{via_str}  (~{total_km:.0f} km){corridor_note}

List 8-12 important stops a driver must know, in order from start to finish.
Include: famous dhaba stops, fuel/food breaks, major cities, cultural landmarks, hill entry points, scenic spots.

Return a JSON array only:
[
  {{
    "name": "<simple lowercase place name — must be geocodable>",
    "type": "<fuel_food|major_city|gateway|mountain_critical|scenic|destination>",
    "note": "<one practical sentence — what makes this stop worth knowing>"
  }}
]

Type guide:
- fuel_food       : famous dhaba or food/fuel stop
- major_city      : large city — ATM, hospital, last highway amenities
- gateway         : road character changes here (hills begin, expressway ends)
- mountain_critical: altitude/weather become a serious factor from here
- scenic          : viewpoint or short detour worth stopping for
- destination     : the final stop

Rules:
- First entry must be {origin} (type: fuel_food), last must be {destination} (type: destination)
- Only include stops that are actually on the route between {origin} and {destination}
- Use common spellings drivers would recognise (e.g. "murthal" not "murthal haryana")
- Notes must be specific and practical — not generic travel advice
- Return ONLY the JSON array, no markdown, no explanation"""

        stops = []
        try:
            raw = await self.call_llm(prompt)
            raw = re.sub(r"```(?:json)?|```", "", raw).strip()
            stops = json.loads(raw)
        except Exception as e:
            print(f"[route_agent] LLM stop discovery failed: {e}")

        # Build cumulative km index for route geometry
        cum_km = self._build_cumulative_km(full_coords)

        checkpoints = []
        seen = set()

        for stop in stops:
            name = (stop.get("name") or "").lower().strip()
            if not name or name in seen:
                continue
            seen.add(name)

            coords = geocode_sync(name)
            if not coords:
                continue  # can't place it on the map — skip

            km = self._km_along_route(coords, full_coords, cum_km) if full_coords else 0.0

            cp_type = stop.get("type", "fuel_food")
            # Only the actual destination gets type "destination"
            if cp_type == "destination" and name != destination:
                cp_type = "fuel_food"

            checkpoints.append({
                "name":          name,
                "coords":        coords,
                "km_from_start": round(km, 1),
                "type":          cp_type,
                "note":          stop.get("note", ""),
                "weather":       None,
                "places":        [],
            })

        checkpoints.sort(key=lambda c: c["km_from_start"])

        # Guarantee origin at 0 km
        origin_coords = geocode_sync(origin)
        checkpoints = [c for c in checkpoints if c["name"] != origin]
        origin_note = next((s.get("note", "") for s in stops if s.get("name", "").lower() == origin), "")
        checkpoints.insert(0, {
            "name": origin, "coords": origin_coords,
            "km_from_start": 0.0, "type": "fuel_food",
            "note": origin_note, "weather": None, "places": [],
        })

        # Guarantee destination is last at total_km — remove any partial matches
        dest_coords = geocode_sync(destination)
        checkpoints = [c for c in checkpoints if destination not in c["name"]]
        dest_note = next((s.get("note", "") for s in stops if s.get("name", "").lower() == destination), "")
        checkpoints.append({
            "name": destination, "coords": dest_coords,
            "km_from_start": round(total_km, 1), "type": "destination",
            "note": dest_note, "weather": None, "places": [],
        })

        return checkpoints

    def _corridor_hint(
        self,
        origin: str,
        destination: str,
        full_coords: list[tuple],
        max_dist_km: float = 25.0,
    ) -> str:
        """
        Find static-dict cities that lie within max_dist_km of the actual
        route geometry, sorted by km from origin.
        This ensures only on-route cities are suggested to the LLM.
        """
        o_coords = geocode_sync(origin)
        if not full_coords or not o_coords:
            return ""

        cum_km = self._build_cumulative_km(full_coords)
        candidates = []

        for city, coords in CITY_COORDS.items():
            if city in (origin, destination):
                continue
            # Find nearest route point
            best_dist = float("inf")
            best_km   = 0.0
            for i, pt in enumerate(full_coords):
                d = haversine_km(coords, pt)
                if d < best_dist:
                    best_dist = d
                    best_km   = cum_km[i]

            if best_dist <= max_dist_km:
                candidates.append((best_km, city))

        candidates.sort()
        return ", ".join(city for _, city in candidates[:14])

    def _build_cumulative_km(self, coords: list[tuple]) -> list[float]:
        """Cumulative km distance at each point along the route."""
        if not coords:
            return []
        cum = [0.0]
        for i in range(1, len(coords)):
            cum.append(cum[-1] + haversine_km(coords[i - 1], coords[i]))
        return cum

    def _km_along_route(
        self,
        point: tuple,
        route_coords: list[tuple],
        cum_km: list[float],
    ) -> float:
        """Return the km-from-start of the route point nearest to `point`."""
        best_km   = 0.0
        best_dist = float("inf")
        for i, coord in enumerate(route_coords):
            d = haversine_km(point, coord)
            if d < best_dist:
                best_dist = d
                best_km   = cum_km[i]
        return best_km

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_toll(self, origin: str, destination: str) -> dict | None:
        key = frozenset({origin.lower(), destination.lower()})
        return TOLL_TABLE.get(key)

    def _get_seasonal_warnings(
        self, places: list[str], month: int
    ) -> list[str]:
        is_himalayan = any(p.lower() in HIMALAYAN_PLACES for p in places)
        if is_himalayan:
            return SEASONAL_WARNINGS.get(month, [])
        return []

    def _clarify_message(self, origin, destination) -> str:
        if origin and not destination:
            return (
                f"Got it — starting from {origin.title()}. "
                "Where are you headed?"
            )
        if destination and not origin:
            return (
                f"Sure! Where are you starting from "
                f"to get to {destination.title()}?"
            )
        return (
            "I need your starting point and destination to plan the route. "
            "Try something like: 'Delhi to Manali' or "
            "'Plan a trip from Delhi to Jaipur via Agra'."
        )

    # ------------------------------------------------------------------
    # Format the trip briefing
    # ------------------------------------------------------------------

    def _format_briefing(self, ctx: dict) -> str:
        origin = ctx["origin"].title()
        dest   = ctx["destination"].title()
        via    = [v.title() for v in ctx.get("via", [])]

        # Header
        if via:
            route_str = " → ".join([origin] + via + [dest])
        else:
            route_str = f"{origin} → {dest}"

        lines = [route_str]

        # Distance + ETA
        if ctx.get("total_km") and ctx.get("total_eta_min"):
            hrs  = ctx["total_eta_min"] // 60
            mins = ctx["total_eta_min"] % 60
            time_str = f"{hrs}h {mins}m" if hrs else f"{mins}m"
            src  = " *(estimated)*" if ctx["route_source"] == "estimated" else ""
            lines.append(f"📍 {ctx['total_km']} km  ·  ⏱ ~{time_str}{src}")

        # Toll
        if ctx.get("toll"):
            t = ctx["toll"]
            lines.append(f"🪙 Toll: ~₹{t['amount']:,} on {t['highway']} (one way)")

        # Checkpoints
        if ctx.get("checkpoints"):
            lines.append("\nCheckpoints:")
            for cp in ctx["checkpoints"]:
                km   = cp["km_from_start"]
                name = cp["name"].title()
                note = cp["note"]
                icon = self._type_icon(cp["type"])
                line = f"  {km:>6.0f} km  {icon} {name}"
                if note:
                    line += f"\n           {note}"
                lines.append(line)

        # Seasonal warnings
        if ctx.get("seasonal_warnings"):
            lines.append("\n⛔ Seasonal alerts:")
            for w in ctx["seasonal_warnings"]:
                lines.append(f"  • {w}")

        return "\n".join(lines)

    def _type_icon(self, cp_type: str) -> str:
        return {
            "fuel_food":         "🍽",
            "major_city":        "🏙",
            "gateway":           "🚧",
            "mountain_critical": "⛰",
            "scenic":            "📸",
            "destination":       "🏁",
        }.get(cp_type, "📍")
