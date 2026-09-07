"""Run the local Brand Atlas API.

Examples:
    python -m backend.main --port 8787 --token dev-token
    python -m backend.main --port 0   # random port for a desktop sidecar
"""

from __future__ import annotations

import argparse
import os
import socket

import uvicorn

try:
    from .app import create_app
except ImportError:  # PyInstaller executes this file outside its package context.
    from backend.app import create_app


def main() -> int:
    parser = argparse.ArgumentParser(description="Brand Atlas local backend")
    parser.add_argument("--host", default=os.getenv("BRAND_ATLAS_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("BRAND_ATLAS_PORT", "8787")))
    parser.add_argument("--token", default=os.getenv("BRAND_ATLAS_TOKEN", "dev-token"))
    args = parser.parse_args()
    os.environ["BRAND_ATLAS_HOST"] = args.host
    os.environ["BRAND_ATLAS_PORT"] = str(args.port)
    os.environ["BRAND_ATLAS_TOKEN"] = args.token
    port = args.port
    if port == 0:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind((args.host, 0))
            port = int(probe.getsockname()[1])
    os.environ["BRAND_ATLAS_PORT"] = str(port)
    app = create_app()
    print(f"BRAND_ATLAS_BACKEND_READY host={args.host} port={port} token={args.token}", flush=True)
    uvicorn.run(app, host=args.host, port=port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
