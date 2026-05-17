"""
agents/places_agent.py
-----------------------
Places / dhabas agent — two modes:

  1. Trip mode  : trip_context exists → find dhabas at every checkpoint along the route
  2. Standalone : no trip planned → search near a named city
"""

import asyncio
from agents.base_agent import BaseAgent
from tools.places import search_nearby, search_along_route
from tools.geocoder import geocode, extract_cities


class PlacesAgent(BaseAgent):
    name = "places"
    description = (
        "Finds dhabas, restaurants, and rest stops along a planned route "
        "or near any Indian city."
    )
    keywords = [
        "dhaba", "dhabas", "restaurant", "eat", "food", "khana", "chai",
        "stop", "rest stop", "petrol", "fuel", "tea stall", "lunch", "dinner",
        "breakfast", "snack", "highway food", "where to eat", "khaana",
    ]

    async def handle(self, query: str, session: dict) -> dict:
        if session.get("trip_context"):
            return await self._enrich_trip_places(session)
        return await self._standalone_places(query, session)

    # ------------------------------------------------------------------
    # Mode 1: search along route geometry and attach to checkpoints
    # ------------------------------------------------------------------

    async def _enrich_trip_places(self, session: dict) -> dict:
        ctx = session["trip_context"]
        checkpoints = ctx.get("checkpoints", [])

        if not checkpoints:
            return self.make_error("No checkpoints found in your trip plan.")

        # Search near each checkpoint concurrently
        results = await asyncio.gather(*[
            search_nearby(cp["coords"], "restaurant")
            for cp in checkpoints
            if cp.get("coords")
        ])

        idx = 0
        for cp in checkpoints:
            if cp.get("coords"):
                cp["places"] = results[idx]
                idx += 1

        lines = [
            f"Food stops along {ctx['origin'].title()} → {ctx['destination'].title()}:\n"
        ]

        for cp in checkpoints:
            places = cp.get("places", [])
            if not places:
                continue
            lines.append(f"📍 {cp['name'].title()} (km {cp['km_from_start']:.0f})")
            for p in places[:3]:
                rating = f"  ⭐{p['rating']}" if p.get("rating") else ""
                lines.append(f"   • {p['name']}{rating}")

        if len(lines) == 1:
            lines.append("No food stops found along this route. Try searching a specific city.")

        return self.make_response("\n".join(lines), data={"trip_context": ctx})

    # ------------------------------------------------------------------
    # Mode 2: standalone city search
    # ------------------------------------------------------------------

    async def _standalone_places(self, query: str, session: dict) -> dict:
        cities = extract_cities(query)
        if not cities:
            return self.make_clarify(
                "Which city or area would you like food options near? "
                "E.g. 'Dhabas in Panipat' or 'Where to eat near Mandi?'"
            )

        city   = cities[0]
        coords = await geocode(city)
        if not coords:
            return self.make_error(f"Could not find location for '{city}'.")

        places = await search_nearby(coords, "restaurant")
        if not places:
            return self.make_response(
                f"No places found near {city.title()}. "
                "This usually means the area is too remote for POI data."
            )

        lines = [f"Food options near {city.title()}:"]
        for p in places:
            rating = f"  ⭐{p['rating']}" if p.get("rating") else ""
            addr   = f"  — {p['address']}" if p.get("address") else ""
            lines.append(f"  • {p['name']}{rating}{addr}")

        return self.make_response("\n".join(lines))