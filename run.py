#!/usr/bin/env python3
"""Entrypoint: launch the anomaly-detection engine + dashboard.

    python run.py            # serve on http://localhost:8000
    python run.py --port 9000
"""

from __future__ import annotations

import argparse

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Agentic AI anomaly detection engine")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    uvicorn.run("backend.app:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
