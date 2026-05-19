"""
tools/corridor.py
-----------------
Web search tool for highway rest stops and food places.

Pipeline per corridor:
  DuckDuckGo HTML search
      -> top 3 URLs
      -> fetch each page via httpx
      -> extract <p> text with BeautifulSoup
      -> LLM condenses into structured stop list
      -> fallback: LLM-only if fetch fails
"""

import re
import json
import asyncio
import httpx
from bs4 import BeautifulSoup

from config import LLM_ENDPOINT, LLM_MODEL

_TIMEOUT   = httpx.Timeout(5.0, connect=3.0)
_MAX_LINKS = 3
_MAX_TEXT  = 2500
_MAX_STOPS = 5

_DDG_URL = "https://html.duckduckgo.com/html/"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; travel-copilot/1.0)"
    )
}


async def search_stops(
    corridor_name: str,
    km_start: float,
    km_end: float,
) -> list[dict]:
    """
    Search the web for rest stops on a named highway corridor.
    Returns list of {"name", "type", "km_approx", "note"}.
    Returns [] on any failure — never raises.
    """
    try:
        query = _build_search_query(corridor_name)
        links = await _fetch_ddg_links(query)

        texts = await asyncio.gather(*[
            _fetch_page_text(link) for link in links[:_MAX_LINKS]
        ])
        combined = "\n\n".join(t for t in texts if t)[:_MAX_TEXT]

        if combined:
            return await _llm_extract_stops(corridor_name, combined)

        return await _llm_fallback_stops(corridor_name, km_start, km_end)

    except Exception as exc:
        print(f"[corridor] search_stops failed for '{corridor_name}': {exc}")
        return []


def _build_search_query(corridor_name: str) -> str:
    return f"best rest stops dhabas food fuel {corridor_name} highway India travellers"


async def _fetch_ddg_links(query: str) -> list[str]:
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True) as client:
        resp = await client.get(_DDG_URL, params={"q": query, "kl": "in-en"})
        resp.raise_for_status()

    soup  = BeautifulSoup(resp.text, "html.parser")
    links = []
    for a in soup.select("a.result__a"):
        href = a.get("href", "")
        if href.startswith("http") and "duckduckgo.com" not in href:
            links.append(href)
        if len(links) >= _MAX_LINKS:
            break
    return links


async def _fetch_page_text(url: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        paragraphs = soup.find_all("p")
        text = " ".join(p.get_text(" ", strip=True) for p in paragraphs)
        return text[:_MAX_TEXT]
    except Exception:
        return ""


async def _llm_extract_stops(corridor_name: str, web_text: str) -> list[dict]:
    prompt = f"""You are extracting highway rest stop information from web content.
Highway: {corridor_name}

Return ONLY a JSON array. Each item must have exactly these fields:
  "name"      : place name (string)
  "type"      : one of dhaba | fuel | rest_area | town
  "km_approx" : approximate km from the start of the trip (integer, 0 if unknown)
  "note"      : one short sentence about why it matters (string)

Rules:
- Maximum {_MAX_STOPS} stops
- Only include stops clearly on or near {corridor_name}
- If nothing useful is found, return []
- Return ONLY the JSON array, no explanation

Web content:
{web_text}"""

    raw = await _call_llm(prompt)
    return _parse_stops(raw)


async def _llm_fallback_stops(corridor_name: str, km_start: float, km_end: float) -> list[dict]:
    prompt = f"""List the most famous rest stops, dhabas, and fuel points on {corridor_name} in India.
The segment runs from approximately {km_start:.0f} km to {km_end:.0f} km from the trip start.

Return ONLY a JSON array. Each item:
  "name"      : place name (string)
  "type"      : one of dhaba | fuel | rest_area | town
  "km_approx" : approximate km from trip start (integer)
  "note"      : one short sentence

Maximum {_MAX_STOPS} stops. If you don't know, return []."""

    raw = await _call_llm(prompt)
    return _parse_stops(raw)


def _parse_stops(raw: str) -> list[dict]:
    """Extract a JSON array from LLM output. Returns [] on any parse failure."""
    try:
        raw = re.sub(r"```(?:json)?|```", "", raw).strip()
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if not match:
            return []
        stops = json.loads(match.group())
        if not isinstance(stops, list):
            return []
        result = []
        for s in stops[:_MAX_STOPS]:
            if not isinstance(s, dict) or not s.get("name"):
                continue
            result.append({
                "name":      str(s.get("name", "")).strip(),
                "type":      str(s.get("type", "dhaba")).strip(),
                "km_approx": int(s.get("km_approx", 0)),
                "note":      str(s.get("note", "")).strip(),
            })
        return result
    except Exception:
        return []


async def _call_llm(prompt: str) -> str:
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        resp = await client.post(
            f"{LLM_ENDPOINT}/api/generate",
            json={"model": LLM_MODEL, "prompt": prompt, "stream": False},
        )
        resp.raise_for_status()
        return resp.json().get("response", "").strip()
