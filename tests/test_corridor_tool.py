"""
tests/test_corridor_tool.py
Tests for the corridor search tool.
Run from project root: python3 -m pytest tests/test_corridor_tool.py -v
"""
import sys, os, asyncio, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

import pytest
from unittest.mock import AsyncMock, patch, MagicMock


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_parse_stops_valid_json():
    from tools.corridor import _parse_stops
    raw = '[{"name":"Murthal","type":"dhaba","km_approx":55,"note":"Famous paranthas"}]'
    result = _parse_stops(raw)
    assert len(result) == 1
    assert result[0]["name"] == "Murthal"
    assert result[0]["type"] == "dhaba"


def test_parse_stops_extracts_json_from_prose():
    from tools.corridor import _parse_stops
    raw = 'Here are the stops: [{"name":"Panipat","type":"fuel","km_approx":90,"note":"Fuel stop"}] Done.'
    result = _parse_stops(raw)
    assert result[0]["name"] == "Panipat"


def test_parse_stops_returns_empty_on_garbage():
    from tools.corridor import _parse_stops
    assert _parse_stops("no json here at all") == []


def test_parse_stops_caps_at_five():
    from tools.corridor import _parse_stops
    stops = [{"name": f"Stop{i}", "type": "dhaba", "km_approx": i*10, "note": ""} for i in range(10)]
    raw = json.dumps(stops)
    result = _parse_stops(raw)
    assert len(result) <= 5


def test_build_search_query_contains_corridor():
    from tools.corridor import _build_search_query
    q = _build_search_query("Delhi Dehradun Expressway")
    assert "Delhi Dehradun Expressway" in q
    assert "rest" in q.lower() or "dhaba" in q.lower() or "food" in q.lower()


def test_search_stops_returns_list():
    from tools.corridor import search_stops

    with patch("tools.corridor._fetch_ddg_links", new_callable=AsyncMock) as mock_links, \
         patch("tools.corridor._fetch_page_text", new_callable=AsyncMock) as mock_page, \
         patch("tools.corridor._llm_extract_stops", new_callable=AsyncMock) as mock_llm:

        mock_links.return_value = ["http://example.com/1"]
        mock_page.return_value = "Murthal is a famous dhaba stop 55km from Delhi."
        mock_llm.return_value = [{"name": "Murthal", "type": "dhaba", "km_approx": 55, "note": "Famous paranthas"}]

        result = run(search_stops("Delhi Dehradun Expressway", 9.9, 92.2))
        assert isinstance(result, list)
        assert result[0]["name"] == "Murthal"


def test_search_stops_returns_empty_list_on_failure():
    from tools.corridor import search_stops

    with patch("tools.corridor._fetch_ddg_links", new_callable=AsyncMock) as mock_links:
        mock_links.side_effect = Exception("Network error")
        result = run(search_stops("Some Highway", 0, 100))
        assert result == []
