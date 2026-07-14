#!/usr/bin/env python3
"""
run_content_studio.py
======================
Convenience launcher for the content-studio web tool.

The directory name ``content-studio`` contains a dash and therefore
cannot be imported with the normal ``import`` statement.  This script
loads the FastAPI app via importlib and hands it to uvicorn.

Usage:
    python tools/run_content_studio.py
    python tools/run_content_studio.py --port 9000
    python tools/run_content_studio.py --host 0.0.0.0
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path


def _load_app():
    here = Path(__file__).resolve().parent
    server_path = here / "content-studio" / "server.py"
    if not server_path.is_file():
        raise SystemExit(f"server.py not found at {server_path}")
    # Make sibling ``four_questions_guard_lib.py`` importable.
    if str(here) not in sys.path:
        sys.path.insert(0, str(here))
    spec = importlib.util.spec_from_file_location("content_studio_server", server_path)
    if spec is None or spec.loader is None:
        raise SystemExit("failed to load content-studio/server.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    if module.app is None:  # pragma: no cover
        raise SystemExit("FastAPI is not installed. Run `pip install fastapi uvicorn`.")
    return module.app


def main() -> int:
    p = argparse.ArgumentParser(description="Run the content-studio web tool")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--reload", action="store_true",
                   help="Reload the server on file changes (development only)")
    args = p.parse_args()

    try:
        import uvicorn  # type: ignore
    except ImportError:
        print("uvicorn is not installed. Run `pip install uvicorn`.", file=sys.stderr)
        return 1

    app = _load_app()
    print(f"content-studio listening on http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info", reload=args.reload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
