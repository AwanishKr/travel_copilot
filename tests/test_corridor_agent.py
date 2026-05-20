"""
tests/test_corridor_agent.py
Tests for the corridor agent (trip mode + standalone mode).
Run from project root: python3 -m pytest tests/test_corridor_agent.py -v
"""
import sys, os, asyncio
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

import pytest
from unittest.mock import AsyncMock, patch


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_trip_mode_writes_corridor_stops_to_context():
    from agents.corridor_agent import CorridorAgent
    agent = CorridorAgent()

    session = {
        "trip_context": {
            "origin": "delhi", "destination": "manali",
            "major_corridors": [
                {"name": "Delhi Dehradun Expressway", "km_start": 9.9, "km_end": 92.2, "length_km": 82.3}
            ],
            "major_cities": [],
        }
    }

    fake_stops = [{"name": "Murthal", "type": "dhaba", "km_approx": 55, "note": "Famous paranthas"}]

    with patch("agents.corridor_agent.search_stops", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = fake_stops
        result = run(agent.handle("suggest stops", session))

    assert result["type"] == "response"
    corridor_stops = session["trip_context"].get("corridor_stops", [])
    assert len(corridor_stops) == 1
    assert corridor_stops[0]["corridor"] == "Delhi Dehradun Expressway"
    assert corridor_stops[0]["stops"] == fake_stops


def test_trip_mode_returns_response_with_stop_names():
    from agents.corridor_agent import CorridorAgent
    agent = CorridorAgent()

    session = {
        "trip_context": {
            "origin": "delhi", "destination": "manali",
            "major_corridors": [
                {"name": "Grand Trunk Road", "km_start": 152.6, "km_end": 235.9, "length_km": 83.2}
            ],
            "major_cities": [],
        }
    }

    fake_stops = [
        {"name": "Karnal", "type": "town", "km_approx": 160, "note": "ATM and fuel"},
        {"name": "Ambala Dhaba", "type": "dhaba", "km_approx": 200, "note": "Good paranthas"},
    ]

    with patch("agents.corridor_agent.search_stops", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = fake_stops
        result = run(agent.handle("food stops", session))

    assert "Karnal" in result["text"] or "Grand Trunk Road" in result["text"]


def test_trip_mode_handles_empty_corridors():
    from agents.corridor_agent import CorridorAgent
    agent = CorridorAgent()

    session = {"trip_context": {"origin": "delhi", "destination": "manali", "major_corridors": [], "major_cities": []}}
    result = run(agent.handle("stops", session))
    assert result["type"] in ("response", "error")


def test_standalone_mode_no_trip_context():
    from agents.corridor_agent import CorridorAgent
    agent = CorridorAgent()

    fake_stops = [{"name": "Murthal", "type": "dhaba", "km_approx": 55, "note": "Famous paranthas"}]

    with patch("agents.corridor_agent.search_stops", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = fake_stops
        result = run(agent.handle("rest stops on Delhi Dehradun Expressway", {}))

    assert result["type"] == "response"
    assert "Murthal" in result["text"]


def test_standalone_mode_no_highway_found_returns_clarify():
    from agents.corridor_agent import CorridorAgent
    agent = CorridorAgent()

    result = run(agent.handle("what should I eat today", {}))
    assert result["type"] == "clarify"
