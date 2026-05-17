"""
agents/hotels_agent.py
-----------------------
Hotels agent — two modes:

  1. Trip mode  : trip_context exists → find hotels at destination (and major stops)
  2. Standalone : no trip planned → find hotels near a named city
"""

import asyncio
from agents.base_agent import BaseAgent
from tools.places import search_nearby
from tools.geocoder import geocode, extract_cities


class HotelsAgent(BaseAgent):
    name = "hotels"
    description = (
        "Finds hotels and stays at the destination or along a planned route."
    )
    keywords = [
        "hotel", "hotels", "stay", "accommodation", "lodge", "lodging",
        "guesthouse", "guest house", "dharamshala", "resort", "hostel",
        "room", "rooms", "book", "raat", "ruko", "rukna", "where to stay",
        "kahan rukein", "night", "sleep",
    ]

    async def handle(self, query: str, session: dict) -> dict:
        if session.get("trip_context"):
            return await self._trip_hotels(session)
        return await self._standalone_hotels(query, session)

    # ------------------------------------------------------------------
    # Mode 1: find hotels at destination + major city checkpoints
    # ------------------------------------------------------------------

    async def _trip_hotels(self, session: dict) -> dict:
        ctx = session["trip_context"]
        checkpoints = ctx.get("checkpoints", [])

        # Search at destination + any "major_city" or "mountain_critical" checkpoints
        priority = [
            cp for cp in checkpoints
            if cp.get("type") in ("destination", "major_city", "mountain_critical")
            and cp.get("coords")
        ]

        if not priority:
            priority = [checkpoints[-1]] if checkpoints else []

        results = await asyncio.gather(*[
            search_nearby(cp["coords"], "lodging")
            for cp in priority
        ])

        lines = [
            f"Hotels along {ctx['origin'].title()} → {ctx['destination'].title()}:\n"
        ]

        for cp, hotels in zip(priority, results):
            if not hotels:
                continue
            lines.append(f"🏨 {cp['name'].title()} (km {cp['km_from_start']:.0f})")
            for h in hotels[:4]:
                rating = f"  ⭐{h['rating']}" if h.get("rating") else ""
                addr   = f"  — {h.get('address', '')}" if h.get("address") else ""
                lines.append(f"   • {h['name']}{rating}{addr}")

        if len(lines) == 1:
            lines.append("No hotel data found for this route.")

        return self.make_response("\n".join(lines), data={"trip_context": ctx})

    # ------------------------------------------------------------------
    # Mode 2: standalone city hotel search
    # ------------------------------------------------------------------

    async def _standalone_hotels(self, query: str, session: dict) -> dict:
        cities = extract_cities(query)
        if not cities:
            return self.make_clarify(
                "Which city are you looking for hotels in? "
                "E.g. 'Hotels in Manali' or 'Where to stay in Jaipur?'"
            )

        city   = cities[0]
        coords = await geocode(city)
        if not coords:
            return self.make_error(f"Could not find location for '{city}'.")

        hotels = await search_nearby(coords, "lodging")
        if not hotels:
            return self.make_response(
                f"No hotel data found near {city.title()}. "
                "Try searching on MakeMyTrip or Booking.com for this area."
            )

        lines = [f"Hotels in {city.title()}:"]
        for h in hotels:
            rating = f"  ⭐{h['rating']}" if h.get("rating") else ""
            addr   = f"  — {h.get('address', '')}" if h.get("address") else ""
            lines.append(f"  • {h['name']}{rating}{addr}")

        return self.make_response("\n".join(lines))