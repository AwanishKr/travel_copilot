"""
agents/router.py
----------------
3-layer routing: keyword → LLM → generic fallback.

Layer 1 — keyword match  : fast, deterministic, works offline
Layer 2 — LLM classify   : handles ambiguous or complex queries
Layer 3 — generic         : catch-all when nothing matches
"""

import re
from agents.base_agent import BaseAgent


class Router:
    def __init__(self, agents: list[BaseAgent]):
        self._agents = {a.name: a for a in agents}
        self._list   = agents

    async def route(self, query: str, session: dict) -> dict:
        # Layer 0: session state — pending route selection always goes to route agent
        if session.get("pending_routes"):
            return await self._agents["route"].handle(query, session)

        # Layer 1a: "[City] to [City]" pattern — always a route query
        if re.search(r"\b\w+\s+to\s+\w+\b", query.lower()):
            return await self._agents["route"].handle(query, session)

        # Layer 1b: keyword match
        agent = self._keyword_match(query)

        # Layer 2: LLM classification
        if agent is None:
            agent = await self._llm_classify(query)

        # Layer 3: generic fallback
        if agent is None:
            agent = self._agents.get("route") or self._list[0]

        return await agent.handle(query, session)

    def _keyword_match(self, query: str) -> BaseAgent | None:
        q = query.lower()
        best       = None
        best_score = 0

        for agent in self._list:
            score = sum(
                1 for kw in agent.keywords
                if re.search(rf"\b{re.escape(kw)}\b", q)
            )
            if score > best_score:
                best_score = score
                best       = agent

        return best if best_score > 0 else None

    async def _llm_classify(self, query: str) -> BaseAgent | None:
        descriptions = "\n".join(
            f"- {a.name}: {a.description}"
            for a in self._list
        )
        prompt = f"""You are a router for a travel assistant.
Given a user query, pick the most appropriate agent name.

Agents:
{descriptions}

Query: "{query}"

Reply with ONLY the agent name (e.g. "route" or "weather"). No explanation."""

        try:
            # Use first available agent's call_llm
            raw = await self._list[0].call_llm(prompt)
            name = raw.strip().lower().split()[0]
            return self._agents.get(name)
        except Exception:
            return None