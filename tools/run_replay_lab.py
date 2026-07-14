#!/usr/bin/env python3
"""
run_replay_lab.py
=================
Launcher for the replay-lab web tool.  Same pattern as
``run_content_studio.py`` — the directory name contains a dash, so
we use importlib to load the FastAPI app.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path


def _load_app():
    here = Path(__file__).resolve().parent
    server_path = here / "replay-lab" / "web.py"
    if not server_path.is_file():
        raise SystemExit(f"web.py not found at {server_path}")
    if str(here) not in sys.path:
        sys.path.insert(0, str(here))
    spec = importlib.util.spec_from_file_location("replay_lab_web", server_path)
    if spec is None or spec.loader is None:
        raise SystemExit("failed to load replay-lab/web.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    if module.app is None:  # pragma: no cover
        raise SystemExit("FastAPI is not installed. Run `pip install fastapi uvicorn`.")
    return module.app


def main() -> int:
    p = argparse.ArgumentParser(description="Run the replay-lab web tool")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8766)
    p.add_argument("--reload", action="store_true")
    args = p.parse_args()
    try:
        import uvicorn  # type: ignore
    except ImportError:
        print("uvicorn is not installed. Run `pip install uvicorn`.", file=sys.stderr)
        return 1
    app = _load_app()
    print(f"replay-lab listening on http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info", reload=args.reload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
