"""
agents/budget_agent.py
-----------------------
Budget estimator — uses trip_context for accurate numbers.

Cost model:
  - Fuel      : distance × fuel_efficiency × fuel_price
  - Toll      : from trip_context (pre-computed static table)
  - Food       : ₹200-400 per person per meal × meals
  - Hotel      : ₹1500-3000 per room per night × nights
"""

import re
import json
from agents.base_agent import BaseAgent


# Fuel price and efficiency defaults (India averages)
FUEL_PRICE_PER_L  = 100.0   # ₹/litre (petrol, approximate)
FUEL_EFFICIENCY   = 15.0    # km/litre (average car)
FOOD_PER_PERSON   = 350     # ₹ per meal (highway dhaba)
HOTEL_PER_ROOM    = 2000    # ₹ per room per night (mid-range)


class BudgetAgent(BaseAgent):
    name = "budget"
    description = (
        "Estimates trip budget including fuel, toll, food, and hotel costs "
        "for a planned route. Uses actual distance from the route plan."
    )
    keywords = [
        "budget", "cost", "kitna paisa", "expense", "kitna lagega", "how much",
        "total cost", "money", "rupee", "rupees", "rs", "inr", "spend",
        "kitna kharcha", "kharcha", "paisa", "price", "estimate",
    ]

    async def handle(self, query: str, session: dict) -> dict:
        ctx = session.get("trip_context")
        if not ctx:
            return self.make_clarify(
                "Plan a route first, then I can estimate the budget. "
                "Try: 'Delhi to Manali'"
            )
        return await self._estimate_budget(query, ctx)

    async def _estimate_budget(self, query: str, ctx: dict) -> dict:
        params = await self._extract_params(query)
        people = params.get("people", 2)
        nights = params.get("nights", 1)
        meals  = params.get("meals_per_day", 2)

        distance_km = ctx.get("total_km", 0)
        toll        = ctx.get("toll", {})
        origin      = ctx["origin"].title()
        destination = ctx["destination"].title()

        # Fuel cost (one way)
        litres     = distance_km / FUEL_EFFICIENCY
        fuel_cost  = round(litres * FUEL_PRICE_PER_L)

        # Toll (one way)
        toll_amount = toll.get("amount", 0) if toll else 0

        # Food (per person, all days)
        total_days = nights + 1
        food_cost  = FOOD_PER_PERSON * meals * people * total_days

        # Hotel (shared room)
        rooms = max(1, people // 2)
        hotel_cost = HOTEL_PER_ROOM * rooms * nights

        total = fuel_cost + toll_amount + food_cost + hotel_cost

        eta_hrs = ctx.get("total_eta_min", 0) // 60
        lines = [
            f"Budget estimate: {origin} → {destination}",
            f"({distance_km} km · {people} people · {nights} night{'s' if nights>1 else ''})\n",
            f"  ⛽ Fuel (one way)    ₹{fuel_cost:,}",
            f"     ({distance_km} km ÷ {FUEL_EFFICIENCY}kmpl × ₹{FUEL_PRICE_PER_L:.0f}/L)",
        ]

        if toll_amount:
            lines.append(f"  🪙 Toll              ₹{toll_amount:,}  ({toll.get('highway', '')})")

        lines += [
            f"  🍽 Food              ₹{food_cost:,}",
            f"     ({meals} meals × ₹{FOOD_PER_PERSON} × {people} people × {total_days} days)",
            f"  🏨 Hotel             ₹{hotel_cost:,}",
            f"     ({rooms} room × ₹{HOTEL_PER_ROOM} × {nights} night{'s' if nights>1 else ''})",
            f"\n  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"  Total (one way)     ₹{total:,}",
            f"  Return trip         ₹{fuel_cost + toll_amount:,} extra (fuel + toll)",
        ]

        if ctx.get("seasonal_warnings"):
            lines.append("\n⚠️ Budget tip: mountain routes may have extra charges (snow chains, permits).")

        return self.make_response("\n".join(lines))

    async def _extract_params(self, query: str) -> dict:
        """Extract people count and nights from query using LLM, falls back to regex."""
        prompt = f"""Extract trip parameters from this query.
Return ONLY a JSON object:
{{"people": <int, default 2>, "nights": <int, default 1>, "meals_per_day": <int, default 2>}}

Query: "{query}"
Reply with ONLY the JSON object."""

        try:
            raw = await self.call_llm(prompt)
            raw = re.sub(r"```(?:json)?|```", "", raw).strip()
            return json.loads(raw)
        except Exception:
            return self._regex_params(query)

    def _regex_params(self, query: str) -> dict:
        q = query.lower()
        people_match = re.search(r"(\d+)\s*(?:people|persons?|log|banda|bandhe|seat)", q)
        nights_match = re.search(r"(\d+)\s*(?:night|raat|din)", q)
        return {
            "people":       int(people_match.group(1)) if people_match else 2,
            "nights":       int(nights_match.group(1)) if nights_match else 1,
            "meals_per_day": 2,
        }