"""
tools/weather.py
----------------
Open-Meteo weather fetcher. No API key needed.

Docs: https://open-meteo.com/en/docs
"""

import httpx

_BASE    = "https://api.open-meteo.com/v1/forecast"
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)

_WMO_CODES = {
    0:  ("Clear sky",        "☀️"),
    1:  ("Mainly clear",     "🌤"),
    2:  ("Partly cloudy",    "⛅"),
    3:  ("Overcast",         "☁️"),
    45: ("Fog",              "🌫"),
    48: ("Icy fog",          "🌫"),
    51: ("Light drizzle",    "🌦"),
    53: ("Drizzle",          "🌦"),
    55: ("Heavy drizzle",    "🌧"),
    61: ("Slight rain",      "🌧"),
    63: ("Rain",             "🌧"),
    65: ("Heavy rain",       "🌧"),
    71: ("Slight snow",      "🌨"),
    73: ("Snow",             "❄️"),
    75: ("Heavy snow",       "❄️"),
    77: ("Snow grains",      "🌨"),
    80: ("Slight showers",   "🌦"),
    81: ("Showers",          "🌧"),
    82: ("Heavy showers",    "⛈"),
    85: ("Snow showers",     "🌨"),
    86: ("Heavy snow showers","❄️"),
    95: ("Thunderstorm",     "⛈"),
    96: ("Thunderstorm + hail","⛈"),
    99: ("Thunderstorm + hail","⛈"),
}


async def get_weather_coords(coords: tuple[float, float]) -> dict | None:
    """
    Get current + 3-day weather for a (lat, lon) point.

    Returns:
        {
            "temp_c":      22,
            "condition":   "Partly cloudy",
            "icon":        "⛅",
            "rain_mm":     0.0,
            "temp_max":    28,
            "temp_min":    15,
            "forecast":    [
                {"date": "2024-06-01", "condition": "Clear sky", "icon": "☀️",
                 "temp_max": 30, "temp_min": 18, "rain_mm": 0.0},
                ...
            ]
        }
    or None on failure.
    """
    lat, lon = coords
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                _BASE,
                params={
                    "latitude":   lat,
                    "longitude":  lon,
                    "current":    "temperature_2m,weathercode,precipitation",
                    "daily":      "temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode",
                    "timezone":   "Asia/Kolkata",
                    "forecast_days": 3,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        current = data.get("current", {})
        daily   = data.get("daily", {})

        wmo     = current.get("weathercode", 0)
        cond, icon = _WMO_CODES.get(wmo, ("Unknown", "🌡"))

        dates    = daily.get("time", [])
        max_temps = daily.get("temperature_2m_max", [])
        min_temps = daily.get("temperature_2m_min", [])
        rain_sums = daily.get("precipitation_sum", [])
        day_wmos  = daily.get("weathercode", [])

        forecast = []
        for i in range(min(3, len(dates))):
            d_wmo = day_wmos[i] if i < len(day_wmos) else 0
            d_cond, d_icon = _WMO_CODES.get(d_wmo, ("Unknown", "🌡"))
            forecast.append({
                "date":      dates[i],
                "condition": d_cond,
                "icon":      d_icon,
                "temp_max":  round(max_temps[i]) if i < len(max_temps) else None,
                "temp_min":  round(min_temps[i]) if i < len(min_temps) else None,
                "rain_mm":   round(rain_sums[i], 1) if i < len(rain_sums) else 0.0,
            })

        return {
            "temp_c":    round(current.get("temperature_2m", 0)),
            "condition": cond,
            "icon":      icon,
            "rain_mm":   current.get("precipitation", 0.0),
            "temp_max":  round(max_temps[0]) if max_temps else None,
            "temp_min":  round(min_temps[0]) if min_temps else None,
            "forecast":  forecast,
        }

    except Exception as e:
        print(f"[weather] Failed for {coords}: {e}")
        return None


def weather_summary(checkpoints: list[dict]) -> str:
    """
    Build a one-line human summary of weather across checkpoints.
    e.g. "Clear until Mandi. Rain expected at Kullu and Manali."
    """
    rain_stops  = []
    snow_stops  = []
    storm_stops = []
    clear_stops = []

    for cp in checkpoints:
        w = cp.get("weather")
        if not w:
            continue
        cond = w.get("condition", "").lower()
        name = cp["name"].title()
        if "snow" in cond or "blizzard" in cond:
            snow_stops.append(name)
        elif "thunder" in cond or "storm" in cond:
            storm_stops.append(name)
        elif "rain" in cond or "drizzle" in cond or "shower" in cond:
            rain_stops.append(name)
        else:
            clear_stops.append(name)

    parts = []
    if storm_stops:
        parts.append(f"⛈ Thunderstorm at {', '.join(storm_stops)}")
    if snow_stops:
        parts.append(f"❄️ Snow at {', '.join(snow_stops)}")
    if rain_stops:
        parts.append(f"🌧 Rain at {', '.join(rain_stops)}")
    if clear_stops and not parts:
        parts.append(f"☀️ Clear skies along the route")

    return "  ".join(parts) if parts else "Weather data unavailable."
