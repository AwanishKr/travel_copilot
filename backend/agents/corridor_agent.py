"""
agents/corridor_agent.py
------------------------
Corridor agent — suggests rest stops and food places along highway segments.

Two modes:
  Trip mode   : trip_context exists -> enrich each corridor via web search
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

    async def _enrich_trip_stops(self, session: dict) -> dict:
        ctx       = session["trip_context"]
        corridors = ctx.get("major_corridors", [])

        if not corridors:
            ctx["corridor_stops"] = []
            return self.make_response("No major highway corridors found for this trip.")

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


def _extract_highway(query: str) -> str | None:
    q = query.strip()
    pattern = r"(?:[\w\s]+(?:expressway|highway|gt road|grand trunk road|nh[\s\-]?\d+|sh[\s\-]?\d+)[\w\s]*)"
    match = re.search(pattern, q, re.IGNORECASE)
    if match:
        return match.group().strip()
    # Use whole-word matching to avoid "sh" matching "should", "nh" matching "enhance", etc.
    q_lower = q.lower()
    for kw in _HIGHWAY_KEYWORDS:
        word_pattern = r"\b" + re.escape(kw) + r"\b"
        if re.search(word_pattern, q_lower):
            return q
    return None
