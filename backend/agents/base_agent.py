"""
agents/base_agent.py
--------------------
BaseAgent — inherited by every agent in the system.

Provides:
  - call_llm()       : async LLM call (Ollama-compatible API)
  - make_response()  : standard success response dict
  - make_error()     : standard error response dict
  - make_clarify()   : standard clarification request dict
"""

import json
import httpx
from config import LLM_ENDPOINT, LLM_MODEL

_TIMEOUT = httpx.Timeout(30.0, connect=5.0)


class BaseAgent:
    name: str = "base"
    description: str = ""
    keywords: list[str] = []

    async def handle(self, query: str, session: dict) -> dict:
        raise NotImplementedError

    async def call_llm(self, prompt: str) -> str:
        """
        Call the LLM (Ollama or Claude API via compatible endpoint).
        Returns the response text, raises on failure.
        """
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                f"{LLM_ENDPOINT}/api/generate",
                json={
                    "model":  LLM_MODEL,
                    "prompt": prompt,
                    "stream": False,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("response", "").strip()

    def make_response(self, text: str, data: dict | None = None) -> dict:
        return {"type": "response", "text": text, "data": data or {}}

    def make_error(self, text: str) -> dict:
        return {"type": "error", "text": text, "data": {}}

    def make_clarify(self, text: str) -> dict:
        return {"type": "clarify", "text": text, "data": {}}
