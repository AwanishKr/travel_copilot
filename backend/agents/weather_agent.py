"""
agents/weather_agent.py
-----------------------
Weather agent — two modes:

  1. Trip mode  : trip_context exists → fetch weather for all checkpoints concurrently
  2. Standalone : no trip planned → answer a direct weather query for a named city
"""

import asyncio
from agents.base_agent import BaseAgent
from tools.weather import get_weather_coords, weather_summary
from tools.geocoder import geocode, extract_cities


class WeatherAgent(BaseAgent):
    name = "weather"
    description = (
        "Gives weather conditions along a planned route or for any Indian city. "
        "Shows temperature, rain, and 3-day forecast."
    )
    keywords = [
        "weather", "mausam", "rain", "barish", "temperature", "garmi",
        "sardi", "cold", "hot", "forecast", "climate", "snow", "baarish",
        "cloudy", "sunny", "storm", "aaandhi", "fog", "dhund",
    ]

    async def handle(self, query: str, session: dict) -> dict:
        if session.get("trip_context"):
            return await self._enrich_trip_weather(session)
        return await self._standalone_weather(query, session)

    # ------------------------------------------------------------------
    # Mode 1: enrich trip_context checkpoints
    # ------------------------------------------------------------------

    async def _enrich_trip_weather(self, session: dict) -> dict:
        ctx = session["trip_context"]
        checkpoints = ctx.get("checkpoints", [])

        if not checkpoints:
            return self.make_error("No checkpoints found in your trip plan.")

        # Fetch all concurrently
        results = await asyncio.gather(*[
            get_weather_coords(cp["coords"])
            for cp in checkpoints
        ])

        for cp, weather in zip(checkpoints, results):
            cp["weather"] = weather

        # Build response text
        lines = [
            f"Weather along {ctx['origin'].title()} → {ctx['destination'].title()}:\n"
        ]
        for cp in checkpoints:
            w = cp.get("weather")
            if not w:
                lines.append(f"  {cp['name'].title()} — data unavailable")
                continue
            lines.append(
                f"  {cp['name'].title():15}  {w['icon']} {w['condition']}"
                f"  {w['temp_c']}°C"
                + (f"  🌧 {w['rain_mm']}mm" if w['rain_mm'] else "")
            )

        summary = weather_summary(checkpoints)
        if summary:
            lines.append(f"\n{summary}")

        return self.make_response("\n".join(lines), data={"trip_context": ctx})

    # ------------------------------------------------------------------
    # Mode 2: standalone city weather query
    # ------------------------------------------------------------------

    async def _standalone_weather(self, query: str, session: dict) -> dict:
        cities = extract_cities(query)

        if not cities:
            return self.make_clarify(
                "Which city's weather would you like? "
                "E.g. 'Weather in Manali' or 'Is it raining in Mumbai?'"
            )

        city = cities[0]
        coords = await geocode(city)
        if not coords:
            return self.make_error(f"Could not find location for '{city}'.")

        weather = await get_weather_coords(coords)
        if not weather:
            return self.make_error(f"Weather data unavailable for {city.title()} right now.")

        w = weather
        lines = [
            f"{city.title()} — {w['icon']} {w['condition']}",
            f"🌡 {w['temp_c']}°C  (High {w['temp_max']}° / Low {w['temp_min']}°)",
        ]
        if w['rain_mm']:
            lines.append(f"🌧 Current precipitation: {w['rain_mm']} mm")

        if w.get("forecast"):
            lines.append("\n3-day forecast:")
            for day in w["forecast"]:
                lines.append(
                    f"  {day['date']}  {day['icon']} {day['condition']}"
                    f"  {day['temp_max']}° / {day['temp_min']}°"
                    + (f"  🌧 {day['rain_mm']}mm" if day['rain_mm'] else "")
                )

        return self.make_response("\n".join(lines))