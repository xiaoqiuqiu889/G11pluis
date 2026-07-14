"""
content-studio/server.py
========================
FastAPI backend for the content-studio — a single-page web tool for
策划 to edit 《革命街没有尽头》 scene contracts and run the
four-questions-guard on every change.

Run it with:
    cd D:/G1-ai-native
    python -m uvicorn tools.content_studio.server:app --port 8765

The server is deliberately small.  It does three things:
  1.  Serve the static ``ui/index.html`` SPA.
  2.  Read / write scene-contract YAML files under
      ``content/<case>/scenes/`` and belief / character files under
      ``content/<case>/beliefs/`` and ``content/<case>/characters/``.
  3.  Run ``four_questions_guard_lib.run_guard`` on every saved
      document and return the structured result to the UI.

No authentication is wired up — the tool is intended for the
策划 workstation behind a VPN.  Do not expose it directly to the
public Internet.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Path setup so ``four_questions_guard_lib`` is importable when the server
# is launched as ``python -m uvicorn tools.content_studio.server:app``.
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve().parent
_TOOLS = _HERE.parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import four_questions_guard_lib as guard  # noqa: E402

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore

try:
    from fastapi import FastAPI, HTTPException  # type: ignore
    from fastapi.middleware.cors import CORSMiddleware  # type: ignore
    from fastapi.responses import FileResponse, JSONResponse  # type: ignore
    from fastapi.staticfiles import StaticFiles  # type: ignore
    from pydantic import BaseModel  # type: ignore
except ImportError:  # pragma: no cover
    FastAPI = None  # type: ignore
    HTTPException = None  # type: ignore
    StaticFiles = None  # type: ignore
    BaseModel = None  # type: ignore
    JSONResponse = None  # type: ignore
    CORSMiddleware = None  # type: ignore


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


REPO_ROOT = Path(__file__).resolve().parents[2]
CONTENT_ROOT = REPO_ROOT / "content"
UI_DIR = _HERE / "ui"

# Make the repo root + tools/ available for template defaults.
DEFAULT_PORT = int(os.environ.get("CONTENT_STUDIO_PORT", "8765"))


# ---------------------------------------------------------------------------
# Pydantic models (only declared when FastAPI is installed)
# ---------------------------------------------------------------------------


if BaseModel is not None:

    class GuardRequest(BaseModel):
        path: str

    class GuardTextRequest(BaseModel):
        text: str
        filename: str | None = None

    class SaveRequest(BaseModel):
        path: str
        text: str

else:  # pragma: no cover - FastAPI not installed
    GuardRequest = None  # type: ignore
    GuardTextRequest = None  # type: ignore
    SaveRequest = None  # type: ignore


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def _build_app() -> Any:
    if FastAPI is None:  # pragma: no cover
        raise RuntimeError(
            "FastAPI is not installed.  Run `pip install fastapi uvicorn` first."
        )

    app = FastAPI(
        title="content-studio",
        version="1.0.0",
        description=(
            "Single-page web tool for editing scene contracts and running "
            "the four-questions-guard on every change."
        ),
    )
    # CORS is wide-open on purpose: the tool is for a workstation behind
    # a VPN.  Tighten this in production.
    app.add_middleware(
        CORSMiddleware,  # type: ignore[arg-type]
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # -----------------------------------------------------------------
    # API routes
    # -----------------------------------------------------------------

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": "1.0.0",
            "guard_version": "1.0.0",
            "content_root": str(CONTENT_ROOT),
        }

    @app.get("/api/cases")
    def list_cases() -> dict[str, Any]:
        """List all cases (= top-level directories under content/)."""
        cases = []
        if CONTENT_ROOT.is_dir():
            for case_dir in sorted(CONTENT_ROOT.iterdir()):
                if not case_dir.is_dir():
                    continue
                scenes = [
                    str(p.relative_to(REPO_ROOT))
                    for p in sorted((case_dir / "scenes").glob("*.yaml"))
                ]
                cases.append({
                    "id": case_dir.name,
                    "path": str(case_dir.relative_to(REPO_ROOT)),
                    "scenes": scenes,
                })
        return {"cases": cases}

    @app.get("/api/file")
    def get_file(path: str) -> dict[str, Any]:
        """Read a YAML / JSON / Markdown file from the repo."""
        target = _resolve_repo_path(path)
        if not target.is_file():
            raise HTTPException(status_code=404, detail=f"file not found: {path}")
        try:
            text = target.read_text(encoding="utf-8")
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"read failed: {exc}") from exc
        return {"path": path, "text": text, "size": len(text)}

    @app.post("/api/guard")
    def run_guard_on_path(req: "GuardRequest") -> dict[str, Any]:
        """Run the 4-questions guard against a file on disk."""
        target = _resolve_repo_path(req.path)
        if not target.is_file():
            raise HTTPException(status_code=404, detail=f"file not found: {req.path}")
        try:
            doc = guard.load_document(str(target))
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"load failed: {exc}") from exc
        report = guard.run_guard(doc, document_path=req.path)
        return report.to_dict()

    @app.post("/api/guard-text")
    def run_guard_on_text(req: "GuardTextRequest") -> dict[str, Any]:
        """Run the 4-questions guard against an in-memory YAML / JSON
        document.  This is what the SPA calls on every "submit" — the
        user clicks the button before saving to disk.
        """
        if yaml is None:  # pragma: no cover
            raise HTTPException(status_code=500, detail="PyYAML is not installed")
        try:
            doc = yaml.safe_load(req.text)
        except yaml.YAMLError as exc:
            return JSONResponse(
                status_code=200,
                content={
                    "document_kind": "unknown",
                    "document_path": req.filename or "<in-memory>",
                    "blocking": True,
                    "blocking_reasons": [f"YAML parse error: {exc}"],
                    "results": [],
                    "summary": {"passed": 0, "failed": 0, "skipped": 0, "total": 0},
                },
            )
        if not isinstance(doc, dict):
            return JSONResponse(
                status_code=200,
                content={
                    "document_kind": "unknown",
                    "document_path": req.filename or "<in-memory>",
                    "blocking": True,
                    "blocking_reasons": [
                        f"document must deserialize to a mapping, got {type(doc).__name__}"
                    ],
                    "results": [],
                    "summary": {"passed": 0, "failed": 0, "skipped": 0, "total": 0},
                },
            )
        report = guard.run_guard(doc, document_path=req.filename or "<in-memory>")
        return report.to_dict()

    @app.post("/api/save")
    def save_file(req: "SaveRequest") -> dict[str, Any]:
        """Write a YAML / JSON file back to disk **iff** the guard
        passes.  The UI can still save when the guard blocks, but the
        response will say so; the CI on the next push will block the
        PR, so the workflow is: edit → guard → save → commit.
        """
        target = _resolve_repo_path(req.path)
        if not target.parent.is_dir():
            raise HTTPException(
                status_code=400,
                detail=f"parent directory does not exist: {target.parent}",
            )
        if yaml is None:  # pragma: no cover
            raise HTTPException(status_code=500, detail="PyYAML is not installed")
        # 1) Parse the in-memory text to make sure it's syntactically valid.
        try:
            doc = yaml.safe_load(req.text)
        except yaml.YAMLError as exc:
            raise HTTPException(status_code=400, detail=f"YAML parse error: {exc}") from exc
        if not isinstance(doc, dict):
            raise HTTPException(
                status_code=400,
                detail=f"document must deserialize to a mapping, got {type(doc).__name__}",
            )
        # 2) Run the guard.
        report = guard.run_guard(doc, document_path=req.path)
        # 3) Write back to disk.  We always write (策划 may want to
        # save a draft, even with blocker reasons), but we tell them
        # clearly in the response.
        try:
            target.write_text(req.text, encoding="utf-8")
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"write failed: {exc}") from exc
        return {
            "saved": True,
            "path": req.path,
            "size": len(req.text),
            "guard": report.to_dict(),
        }

    # -----------------------------------------------------------------
    # Static UI
    # -----------------------------------------------------------------
    if UI_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(UI_DIR)), name="static")

        @app.get("/")
        def root() -> Any:
            index = UI_DIR / "index.html"
            if not index.is_file():  # pragma: no cover
                raise HTTPException(status_code=404, detail="UI not built")
            return FileResponse(str(index))

    return app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_repo_path(path: str) -> Path:
    """Resolve a repo-relative path to an absolute Path, with safety
    checks.  Rejects paths that escape the repo root.
    """
    candidate = (REPO_ROOT / path).resolve()
    try:
        candidate.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"path escapes repo root: {path}",
        ) from exc
    return candidate


# Module-level app for ``uvicorn tools.content_studio.server:app``.
app = _build_app() if FastAPI is not None else None  # type: ignore


# ---------------------------------------------------------------------------
# CLI launcher — `python -m tools.content_studio.server [port]`
# ---------------------------------------------------------------------------


def _main() -> int:  # pragma: no cover
    import argparse

    p = argparse.ArgumentParser(description="Launch the content-studio server")
    p.add_argument("--port", type=int, default=DEFAULT_PORT, help="port to listen on")
    p.add_argument("--host", type=str, default="127.0.0.1", help="host to bind")
    args = p.parse_args()

    try:
        import uvicorn  # type: ignore
    except ImportError:
        print("uvicorn is not installed.  Run `pip install uvicorn` first.", file=sys.stderr)
        return 1

    if app is None:
        print("FastAPI is not installed.  Run `pip install fastapi` first.", file=sys.stderr)
        return 1

    print(f"content-studio listening on http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
