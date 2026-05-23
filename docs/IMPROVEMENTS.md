# Output Review — Improvement Plan

## What's solid, don't touch
- Route alternatives (3 routes, accurate distances/ETAs)
- City sequence from reverse geocoder (accurate, granular)
- Weather gradient (temperature drop with altitude is physically correct)
- Corridor extraction from Mappls steps

---

## 1. Corridor naming — contextualise for the trip

**Problem:** "Chandigarh Jalandhar Expressway" and "Delhi Dehradun Expressway"
are factually correct road names but misleading — user is going to Manali,
not Jalandhar or Dehradun.

**Fix:** In the LLM enrichment layer, add trip context when describing corridors.

```
Input to LLM:
  Trip: Delhi → Manali
  Corridor: "Chandigarh Jalandhar Expressway", km 274–287

LLM should output:
  "NH-44 — you take this toward Kiratpur, not Jalandhar.
   Exit at Kiratpur Sahib for the Manali highway."
```

**Where:** LLM enrichment layer (Step 3). Do NOT change route_filter.py.

---

## 2. Missing corridor — Panipat to Ambala (km 97–237)

**Problem:** 140km gap between "Delhi Panipat Expressway" (ends km 97) and
"Ambala Chandigarh Expressway" (starts km 237). This stretch — Karnal,
Nilokheri, Thanesar, Shahabad — has no corridor name even though it's
the busiest part of NH-44.

**Why:** Mappls doesn't tag this stretch with an expressway name — it's
just "Grand Trunk Road" or "NH-44" in their database without a corridor label.

**Fix:** In route_filter.py, add "NH" and "GT Road" variants to
`_MAJOR_ROAD_KEYWORDS` so this stretch gets captured as a corridor:

```python
_MAJOR_ROAD_KEYWORDS = [
    "Expressway", "Express Way", "Highway", "Grand Trunk Road", "GT Road",
    "National Highway", "State Highway",
    "NH-", "NH ",          # ← add these two
]
```

**Where:** `tools/route_filter.py` — one line change.

---

## 3. LLM enrichment layer (Step 3) — not built yet

**What it should do:** For each checkpoint in the cities list, add a one-line
note a driver would actually find useful.

**Input:** checkpoint name + km_from_start + corridor context + trip origin/destination

**Output per checkpoint:**
```
Murthal (km 55)   → "Famous dhaba strip on GT Road — best breakfast stop leaving Delhi"
Karnal (km 118)   → "Good fuel and food options. Last comfortable stop before Ambala."
Anandpur Sahib (km 310) → "Entering hills. Road quality changes after this."
Pandoh (km 440)   → "Pandoh Dam viewpoint. Road narrows significantly here."
```

**Rules for the LLM prompt:**
- One sentence per checkpoint, max
- Must be specific to this route and this city, not generic
- Classify type from note: fuel_food / gateway / scenic / mountain_critical / destination
- If LLM is offline, leave note empty — don't block the response

**Where:** New function `enrich_checkpoints()` in `agents/route_agent.py`
or a dedicated `agents/enrichment_agent.py`.

---

## Priority order

1. `route_filter.py` — add NH keyword (5 min, one line)
2. LLM enrichment layer — main feature to build next
3. Corridor contextualisation — part of enrichment layer, not separate work
