"""
main.py
-------
FastAPI + Jinja2 server with in-memory session store.

Routes:
  GET  /          → chat UI
  POST /chat      → message handler (returns JSON)
  GET  /session   → current session state (for debugging)
  POST /reset     → clear current session
"""

import uuid
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Cookie, Response
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from agents import build_router
from config import SESSION_TTL

# ---------------------------------------------------------------------------
# Session store — simple in-memory dict, keyed by session ID cookie
# ---------------------------------------------------------------------------

_sessions: dict[str, dict] = {}
_session_ts: dict[str, float] = {}


def get_session(session_id: str) -> dict:
    _session_ts[session_id] = time.time()
    return _sessions.setdefault(session_id, {})


def _prune_sessions():
    now = time.time()
    dead = [k for k, ts in _session_ts.items() if now - ts > SESSION_TTL]
    for k in dead:
        _sessions.pop(k, None)
        _session_ts.pop(k, None)


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.router = build_router()
    yield

app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request, session_id: str = Cookie(default=None)):
    sid = session_id or str(uuid.uuid4())
    response = templates.TemplateResponse(request=request, name="chat.html")
    response.set_cookie("session_id", sid, max_age=SESSION_TTL, httponly=True)
    return response


@app.post("/chat")
async def chat(
    request: Request,
    session_id: str = Cookie(default=None),
):
    _prune_sessions()

    sid = session_id or str(uuid.uuid4())
    session = get_session(sid)

    body = await request.json()
    query = (body.get("message") or "").strip()

    if not query:
        return JSONResponse({"type": "error", "text": "Empty message."})

    router = request.app.state.router
    result = await router.route(query, session)

    response = JSONResponse(result)
    response.set_cookie("session_id", sid, max_age=SESSION_TTL, httponly=True)
    return response


@app.get("/session")
async def session_state(session_id: str = Cookie(default=None)):
    if not session_id:
        return JSONResponse({"error": "No session."})
    session = _sessions.get(session_id, {})
    # Serialize trip_context (strip non-serializable coords if needed)
    return JSONResponse({"session_id": session_id, "keys": list(session.keys())})


@app.post("/reset")
async def reset_session(session_id: str = Cookie(default=None)):
    if session_id and session_id in _sessions:
        _sessions[session_id] = {}
    return JSONResponse({"ok": True})


# ---------------------------------------------------------------------------
# Dev entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)