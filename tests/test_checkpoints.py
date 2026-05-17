"""
tests/test_checkpoints.py
--------------------------
Tests the full checkpoint discovery pipeline:
  query → route → LLM-discovered stops with context

This is the core value-add over a plain maps app:
every stop comes with WHY it matters to the driver.

Run: python3 tests/test_checkpoints.py
Run custom: python3 tests/test_checkpoints.py --from Delhi --to Manali
"""

import asyncio
import argparse
from helpers import header, ok, err, skip, dim, HDR, END


CHECKPOINT_ICONS = {
    "fuel_food":         "🍽 ",
    "major_city":        "🏙 ",
    "gateway":           "🚧 ",
    "mountain_critical": "⛰ ",
    "scenic":            "📸 ",
    "destination":       "🏁 ",
}

CHECKPOINT_LABELS = {
    "fuel_food":         "Food & Fuel",
    "major_city":        "Major City",
    "gateway":           "Route Gateway",
    "mountain_critical": "Mountain Zone",
    "scenic":            "Scenic Stop",
    "destination":       "Destination",
}


async def run(source: str, destination: str):
    from agents.route_agent import RouteAgent

    print(f"""
{HDR}Checkpoint Discovery Test{END}
{"=" * 60}
Route   : {source.title()} → {destination.title()}
Testing : Route + smart stop discovery (why each stop matters)
{"=" * 60}
""")

    # ----------------------------------------------------------------
    # Step 1: Run the route agent
    # ----------------------------------------------------------------
    header("Step 1 — Running route agent")

    agent   = RouteAgent()
    session = {}
    query   = f"{source} to {destination}"

    result = await agent.handle(query, session)

    if result["type"] == "error":
        err(f"Agent failed: {result['text']}")
        return
    if result["type"] == "clarify":
        err(f"Agent needs clarification: {result['text']}")
        return

    ok("Route agent returned successfully")

    ctx = session.get("trip_context")
    if not ctx:
        err("No trip_context in session")
        return

    total_km  = ctx.get("total_km", 0)
    total_min = ctx.get("total_eta_min", 0)
    hrs       = total_min // 60
    mins      = total_min % 60
    toll      = ctx.get("toll")
    source_   = ctx.get("route_source", "unknown")

    ok(f"Distance  : {total_km} km")
    ok(f"Duration  : {hrs}h {mins}m")
    ok(f"Toll      : ₹{toll['amount']} on {toll['highway']}" if toll else "Toll : none / unknown")
    ok(f"Source    : {source_}")

    checkpoints = ctx.get("checkpoints", [])
    ok(f"Stops     : {len(checkpoints)} checkpoints discovered")

    warnings = ctx.get("seasonal_warnings", [])
    if warnings:
        ok(f"Alerts    : {len(warnings)} seasonal warning(s)")

    # ----------------------------------------------------------------
    # Step 2: Display the route card (what a maps app shows)
    # ----------------------------------------------------------------
    header("Step 2 — Route card (what Google Maps shows)")

    print(f"  {source.title()} → {destination.title()}")
    print(f"  {total_km} km  ·  {hrs}h {mins}m drive\n")

    plain_stops = " → ".join(cp["name"].title() for cp in checkpoints)
    print(f"  {plain_stops}")

    # ----------------------------------------------------------------
    # Step 3: Enriched checkpoint view (what our agent adds)
    # ----------------------------------------------------------------
    header("Step 3 — Enriched stops (our co-driver layer)")

    print(f"  {'KM':>5}  {'TYPE':<18}  STOP + WHY IT MATTERS")
    print(f"  {'—'*5}  {'—'*18}  {'—'*40}")

    has_notes = 0
    for cp in checkpoints:
        km    = cp["km_from_start"]
        name  = cp["name"].title()
        ctype = cp.get("type", "fuel_food")
        note  = cp.get("note", "").strip()
        icon  = CHECKPOINT_ICONS.get(ctype, "📍 ")
        label = CHECKPOINT_LABELS.get(ctype, ctype)

        print(f"  {km:>5.0f}  {icon}{label:<16}  {name}")
        if note:
            print(f"  {'':>5}  {'':>18}  ↳ {note}")
            has_notes += 1
        else:
            print(f"  {'':>5}  {'':>18}  ↳ (no note — Ollama may be offline)")

    # ----------------------------------------------------------------
    # Step 4: Assertions
    # ----------------------------------------------------------------
    header("Step 4 — Assertions")

    ok("Route returned") if total_km > 0 else err("No distance")
    ok("Duration returned") if total_min > 0 else err("No ETA")

    if len(checkpoints) >= 4:
        ok(f"{len(checkpoints)} checkpoints (expected ≥ 4)")
    else:
        err(f"Only {len(checkpoints)} checkpoints — LLM may be offline or model too weak")

    if has_notes >= len(checkpoints) // 2:
        ok(f"{has_notes}/{len(checkpoints)} stops have enriched notes")
    else:
        skip(f"Only {has_notes}/{len(checkpoints)} stops have notes — start Ollama for full enrichment")

    first = checkpoints[0]["name"]
    last  = checkpoints[-1]["name"]
    if first == source.lower():
        ok(f"First stop is origin ({source.title()})")
    else:
        err(f"First stop is '{first}' — expected '{source.lower()}'")

    if last == destination.lower():
        ok(f"Last stop is destination ({destination.title()})")
    else:
        err(f"Last stop is '{last}' — expected '{destination.lower()}'")

    kms = [cp["km_from_start"] for cp in checkpoints]
    if kms == sorted(kms):
        ok("Stops are in km order")
    else:
        err("Stops are out of order")

    if warnings:
        print()
        for w in warnings:
            print(f"  ⚠️  {w}")

    print(f"\n{'=' * 60}")
    print(f"  Summary: {len(checkpoints)} stops, {has_notes} enriched")
    print(f"  {'=' * 60}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Checkpoint discovery test")
    parser.add_argument("--from", dest="source",      default="Delhi",  metavar="CITY")
    parser.add_argument("--to",   dest="destination", default="Manali", metavar="CITY")
    args = parser.parse_args()

    asyncio.run(run(args.source, args.destination))
