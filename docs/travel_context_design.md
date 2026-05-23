# Travel Copilot — Route Filter & Travel Context Design

## Goal

Convert the huge raw route JSON from the Mappls Directions API into a compact, semantic `travel_context` that downstream agents can understand and use.

The downstream agents are:
- Weather Agent
- Dhaba/Rest Stop Agent
- Scenic Recommendation Agent
- Fatigue/Travel Advisory Agent

---

# Step 1 — Receive Raw Route JSON

Input:
```text
Mappls Directions API response
```

This contains:
- road graph data
- maneuver instructions
- geometry
- intersections
- road names
- ETA
- distances

Problem:
- too large
- too granular
- not semantically useful for AI agents

---

# Step 2 — Apply Deterministic Route Filter

The filter compresses the route into meaningful travel structure.

## Remove Noise

Discard:
- unnamed roads
- lane changes
- flyovers
- tiny turns
- ramps
- maneuver-only segments

Because these are:
```text
navigation details
```

not:
```text
travel context
```

---

## Keep Important Road Segments

Preserve:
- National Highways (NH)
- Important State Highways (SH)
- Expressways
- Long continuous corridors

Examples:
- NH44
- NH154
- Delhi Panipat Expressway

These become:
```text
major travel corridors
```

---

## Extract Major Cities

Using route coordinates:
- sample route every X km
- reverse geocode
- extract nearby cities/towns
- remove duplicates

Examples:
- Delhi
- Karnal
- Chandigarh
- Mandi
- Kullu
- Manali

These become:
```text
semantic anchors
```

for downstream agents.

---

## Extract Major Checkpoints

Examples:
- Murthal
- Toll zones
- Hill entry points
- Major rest corridors
- Scenic transitions

These checkpoints help:
- dhaba recommendation
- weather prediction
- fatigue estimation

---

# Step 3 — Build travel_context

The filter outputs a compact structured object.

Example schema:

```json
{
  "trip_summary": {
    "start": "Delhi",
    "destination": "Manali",
    "total_distance_km": 497,
    "estimated_duration_hr": 8.2
  },

  "major_corridors": [
    "NH44",
    "NH154",
    "Delhi Panipat Expressway"
  ],

  "major_cities": [
    "Delhi",
    "Karnal",
    "Chandigarh",
    "Mandi",
    "Kullu",
    "Manali"
  ],

  "semantic_checkpoints": [
    "Murthal",
    "Bilaspur",
    "Hill Entry Zone"
  ],

  "travel_phases": [
    "Urban Exit",
    "Highway Cruise",
    "Hill Ascent",
    "Mountain Corridor"
  ]
}
```

---

# Why travel_context is Important

The `travel_context` becomes:
```text
shared semantic memory
```

for all downstream agents.

Instead of each agent processing:
- raw coordinates
- huge route JSON
- low-level navigation data

they consume:
```text
compact human-like travel understanding
```

---

# Step 4 — Downstream Agent Usage

## Weather Agent

Consumes:
- major cities
- checkpoints

Outputs:
```text
Heavy rain expected near Mandi.
```

---

## Dhaba Agent

Consumes:
- highways
- checkpoints
- travel phases

Outputs:
```text
Good food/rest stop near Murthal in 30 km.
```

---

## Scenic Agent

Consumes:
- terrain transitions
- hill entry points

Outputs:
```text
Mountain views begin after Bilaspur.
```

---

# Final Architecture

```text
Mappls Directions API
        ↓
Raw Route JSON
        ↓
Deterministic Filter Layer
        ↓
travel_context
        ↓
LLM Context Synthesis
        ↓
Specialized Travel Agents
```

---

# Core Design Philosophy

The system should behave like:
```text
an experienced long-distance driver
```

who understands:
- highways
- major cities
- rest points
- weather zones
- terrain transitions

instead of behaving like:
```text
a simple GPS navigation engine
```
