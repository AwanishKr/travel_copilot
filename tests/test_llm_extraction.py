"""
tests/test_llm_extraction.py
-----------------------------
Tests the LLM's ability to extract source and destination from
natural language queries.

Requires Ollama running with qwen2.5:3b.
Run: python3 tests/test_llm_extraction.py
"""

import asyncio
import json
import re
from helpers import header, ok, err, skip, dim

QUERIES = [
    # (query, expected_origin, expected_destination, expected_via)
    ("I want to go from Delhi to Manali",         "delhi",   "manali",  []),
    ("Plan a trip from Mumbai to Pune",            "mumbai",  "pune",    []),
    ("Delhi to Jaipur via Agra",                  "delhi",   "jaipur",  ["agra"]),
    ("How far is Chandigarh from Delhi?",          "delhi",   "chandigarh", []),
    ("Mujhe Delhi se Manali jana hai",             "delhi",   "manali",  []),   # Hindi
    ("fastest route from Bangalore to Mysore",     "bangalore","mysore", []),
    ("Delhi Agra Jaipur road trip",               "delhi",   "jaipur",  ["agra"]),
]


async def run():
    import sys
    from agents.base_agent import BaseAgent

    header("LLM Entity Extraction")
    print("  Tests LLM parsing of natural language → origin / destination\n")

    agent = BaseAgent()

    # Quick connectivity check
    try:
        await agent.call_llm("Reply with the word OK only.")
    except Exception as e:
        skip(f"Ollama not reachable ({e}). Start with: ollama serve")
        return

    passed = failed = 0

    for query, exp_origin, exp_dest, exp_via in QUERIES:
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

Query: "{query}"

Reply with ONLY the JSON object, nothing else."""

        try:
            raw = await agent.call_llm(prompt)
            raw = re.sub(r"```(?:json)?|```", "", raw).strip()
            result = json.loads(raw)

            origin = (result.get("origin") or "").lower().strip()
            dest   = (result.get("destination") or "").lower().strip()
            via    = [v.lower().strip() for v in (result.get("via") or [])
                      if str(v).lower() not in ("null", "none", "")]

            origin_ok = origin == exp_origin
            dest_ok   = dest   == exp_dest
            via_ok    = set(via) == set(exp_via)

            if origin_ok and dest_ok and via_ok:
                ok(f'"{query}"')
                dim(f'     → {origin} → {dest}' + (f' via {via}' if via else ''))
                passed += 1
            else:
                err(f'"{query}"')
                dim(f'     expected : {exp_origin} → {exp_dest}' + (f' via {exp_via}' if exp_via else ''))
                dim(f'     got      : {origin} → {dest}' + (f' via {via}' if via else ''))
                failed += 1

        except Exception as e:
            err(f'"{query}" — parse error: {e}')
            dim(f'     raw output: {raw[:120]}')
            failed += 1

    print(f"\n  Result: {passed} passed, {failed} failed out of {len(QUERIES)}")


if __name__ == "__main__":
    asyncio.run(run())
