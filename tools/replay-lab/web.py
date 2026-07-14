"""
replay-lab/web.py
=================
Web frontend for the replay-lab.

Run with:
    python tools/run_replay_lab.py
    python tools/run_replay_lab.py --port 8766

Endpoints:
    GET  /              — single-page UI
    POST /api/replay    — accept { snapshot, events } in JSON and return
                          the replay result
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_TOOLS = _HERE.parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

# Re-use the content-studio server's FastAPI knowledge if available.
try:
    from fastapi import FastAPI, HTTPException  # type: ignore
    from fastapi.middleware.cors import CORSMiddleware  # type: ignore
    from fastapi.responses import FileResponse  # type: ignore
    from fastapi.staticfiles import StaticFiles  # type: ignore
    from pydantic import BaseModel  # type: ignore
except ImportError:  # pragma: no cover
    FastAPI = None  # type: ignore
    BaseModel = None  # type: ignore
    HTTPException = None  # type: ignore
    StaticFiles = None  # type: ignore
    FileResponse = None  # type: ignore
    CORSMiddleware = None  # type: ignore

import replay  # noqa: E402
import four_questions_guard_lib as guard  # noqa: E402

UI_DIR = _HERE / "ui"


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


if BaseModel is not None:

    class ReplayRequest(BaseModel):
        snapshot: dict[str, Any] | None = None
        events: list[dict[str, Any]]
        run_id: str | None = None
        stop_at: int | None = None
        guard: bool = False

else:  # pragma: no cover
    ReplayRequest = None  # type: ignore


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def _build_app() -> Any:
    if FastAPI is None:  # pragma: no cover
        raise RuntimeError("FastAPI is not installed.  Run `pip install fastapi uvicorn`.")

    app = FastAPI(title="replay-lab", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,  # type: ignore[arg-type]
        allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "version": "1.0.0"}

    @app.post("/api/replay")
    def replay_endpoint(req: "ReplayRequest") -> dict[str, Any]:
        if not req.events:
            raise HTTPException(status_code=400, detail="events list is empty")
        try:
            entries = [replay._entry_from_dict(item) for item in req.events]
        except (KeyError, ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=f"invalid event: {exc}") from exc
        if req.snapshot is None:
            snapshot = replay.make_initial_snapshot(runId=req.run_id)
        else:
            snapshot = req.snapshot
        if req.run_id is not None:
            snapshot["runId"] = req.run_id
        result = replay.replay(snapshot, entries, runId=req.run_id, stop_at=req.stop_at)

        if req.guard:
            for ev, trace_entry in zip(entries, result.trace):
                interaction_doc = {
                    "artifact_updates": ev.artifact_updates,
                    "event_log": ev.event_log,
                    "belief_updates": ev.belief_updates,
                    "turn_budget": {
                        "current_turn": ev.turn_index,
                        "max_turns": ev.raw.get("max_turns"),
                    } if ev.turn_index is not None else {},
                    "action_whitelist": ev.raw.get("action_whitelist", []),
                    "causal_seeds": ev.causal_seeds,
                    "far_echo_routes": ev.raw.get("far_echo_routes", []),
                }
                report = guard.run_guard(
                    interaction_doc,
                    document_path=f"event:{ev.eventSequence}",
                )
                trace_entry.applied.append(
                    f"guard:{'PASS' if not report.blocking else 'BLOCK'}"
                )
                if report.blocking:
                    trace_entry.skipped.extend(report.blocking_reasons)

        return result.to_dict()

    if UI_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(UI_DIR)), name="static")

        @app.get("/")
        def root() -> Any:
            index = UI_DIR / "index.html"
            if not index.is_file():  # pragma: no cover
                raise HTTPException(status_code=404, detail="UI not built")
            return FileResponse(str(index))

    return app


app = _build_app() if FastAPI is not None else None  # type: ignore


# ---------------------------------------------------------------------------
# CLI launcher
# ---------------------------------------------------------------------------


def _main() -> int:  # pragma: no cover
    import argparse
    p = argparse.ArgumentParser(description="Run the replay-lab web tool")
    p.add_argument("--port", type=int, default=8766)
    p.add_argument("--host", default="127.0.0.1")
    args = p.parse_args()
    try:
        import uvicorn  # type: ignore
    except ImportError:
        print("uvicorn is not installed. Run `pip install uvicorn`.", file=sys.stderr)
        return 1
    if app is None:
        print("FastAPI is not installed. Run `pip install fastapi`.", file=sys.stderr)
        return 1
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
