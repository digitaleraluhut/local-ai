#!/usr/bin/env python3
"""
Container entry-point stub.
Imports and runs the main app from main.py.
This file exists so systemd pkill can match "comfyui-bridge.py" in the process list.
"""

import os
import sys

# Ensure sibling modules (bridge.py, routes.py, mcp_tools.py, main.py) are importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import app  # noqa: F401

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("BRIDGE_PORT", "8082"))
    uvicorn.run(app, host="0.0.0.0", port=port)
