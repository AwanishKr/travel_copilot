"""
tools/mappls.py
---------------
Mappls (MapmyIndia) Routing API wrapper.

Auth    : Static key as ?access_token= query param (no OAuth needed)
Endpoint: https://route.mappls.com/route/direction/route_adv/driving/{coords}
Docs    : https://developer.mappls.com/documentation/sdk/rest-apis/mappls-routing-api/readme/

Key notes:
  - Coordinates are lon,lat (not lat,lon) separated by semicolons
  - Default geometry is polyline6 (6-digit precision) — pass precision=6 to decode()
  - alternatives=true returns up to 2-3 route options
  - toll/motorway fields > 0 mean the route contains those features
  - steps=true adds turn-by-turn with road names per leg
"""

import httpx
from config import MAPPLS_KEY

_BASE    = "https://route.mappls.com/route/direction/route_adv/driving"
_TIMEOUT = httpx.Timeout(15.0, connect=5.0)


async def get_directions(
    origin: tuple[float, float],
    destination: tuple[float, float],
    via: list[tuple[float, float]] | None = None,
    alternatives: bool = True,
    steps: bool = True,
) -> dict | None:
    """
    Get driving directions between coordinates using Mappls.

    Args:
        origin      : (lat, lon) start point
        destination : (lat, lon) end point
        via         : optional list of (lat, lon) intermediate stops
        alternatives: request up to 2 alternate routes
        steps       : include turn-by-turn steps with road names

    Returns dict or None on failure:
        {
            "routes": [
                {
                    "geometry":   "polyline6_encoded_string",
                    "distance_m": 497380,
                    "duration_s": 29700,
                    "has_toll":   True,
                    "steps": [
                        {
                            "name":        "NH-44",
                            "distance_m":  87000,
                            "duration_s":  4500,
                            "instruction": "Head north on NH-44",
                            "geometry":    "polyline6_encoded_string",
                        },
                        ...
                    ],
                },
                ...  # alternate routes if available
            ]
        }

    IMPORTANT: Mappls geometry uses polyline6 (6-digit precision).
    Always decode with: polyline.decode(geometry, precision=6)
    """
    if not MAPPLS_KEY:
        print("[mappls] No MAPPLS_KEY in .env")
        return None

    # Mappls expects lon,lat order, semicolon-separated
    all_points = [origin] + (via or []) + [destination]
    coord_str  = ";".join(f"{lon},{lat}" for lat, lon in all_points)

    params = {
        "alternatives": "true" if alternatives else "false",
        "steps":        "true" if steps else "false",
        "geometries":   "polyline6",   # 6-digit precision
        "overview":     "full",        # full route geometry
        "access_token": MAPPLS_KEY,
    }

    url = f"{_BASE}/{coord_str}"

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        if data.get("code") != "Ok":
            print(f"[mappls] API error: {data.get('code')} — {data.get('message', '')}")
            return None

        routes = []
        for r in data.get("routes", []):
            # Flatten steps from all legs
            all_steps = []
            for leg in r.get("legs", []):
                for step in leg.get("steps", []):
                    name = (step.get("name") or "").strip()
                    dist = step.get("distance", 0)
                    dur  = step.get("duration", 0)
                    geom = step.get("geometry", "")
                    maneuver = step.get("maneuver", {})

                    # Skip trivial steps (arrive/depart with no road name)
                    if dist < 50 and not name:
                        continue

                    all_steps.append({
                        "name":        name or "Unnamed road",
                        "distance_m":  round(dist),
                        "duration_s":  round(dur),
                        "instruction": maneuver.get("instruction", ""),
                        "geometry":    geom,
                    })

            routes.append({
                "geometry":   r.get("geometry", ""),
                "distance_m": round(r.get("distance", 0)),
                "duration_s": round(r.get("duration", 0)),
                "has_toll":   r.get("toll", 0) > 0,
                "steps":      all_steps,
            })

        return {"routes": routes} if routes else None

    except httpx.HTTPStatusError as e:
        print(f"[mappls] HTTP {e.response.status_code}: {e.response.text[:200]}")
        return None
    except Exception as e:
        print(f"[mappls] Failed: {e}")
        return None


async def check_key() -> dict:
    """
    Verify the Mappls key works by running a short test route.
    Delhi → Connaught Place (~5km) — fast and cheap to call.
    """
    if not MAPPLS_KEY:
        return {"ok": False, "message": "No MAPPLS_KEY in .env"}

    result = await get_directions(
        origin=(28.6139, 77.2090),       # Delhi
        destination=(28.6304, 77.2177),  # Connaught Place
        alternatives=False,
        steps=False,
    )

    if result and result.get("routes"):
        r  = result["routes"][0]
        km = r["distance_m"] / 1000
        return {
            "ok":      True,
            "message": f"Mappls key working. Test route: {km:.1f} km",
        }

    return {"ok": False, "message": "Mappls key invalid or API error"}
