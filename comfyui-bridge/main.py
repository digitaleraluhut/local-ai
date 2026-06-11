#!/usr/bin/env python3
"""
Entry point for the ComfyUI OpenAI bridge.
Creates the FastAPI app, wires MCP lifespan, includes REST routes.
"""

import contextlib
import os

from fastapi import FastAPI
from mcp.server.fastmcp.server import StreamableHTTPASGIApp
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

from mcp_tools import mcp
from routes import router

_mcp_session_manager = StreamableHTTPSessionManager(
    app=mcp._mcp_server,
    json_response=True,
    stateless=True,
)
_mcp_handler = StreamableHTTPASGIApp(_mcp_session_manager)


@contextlib.asynccontextmanager
async def _lifespan(app: FastAPI):
    async with _mcp_session_manager.run():
        yield


app = FastAPI(title="ComfyUI OpenAI Bridge", lifespan=_lifespan)
app.add_route("/mcp", _mcp_handler, methods=["GET", "POST", "DELETE"])
app.include_router(router)


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("BRIDGE_PORT", "8082"))
    uvicorn.run(app, host="0.0.0.0", port=port)
