#!/usr/bin/env python3
"""
OpenAI-compatible API bridge for ComfyUI.
Shared utilities, config, and models used by routes.py and mcp_tools.py.

Entry point: main.py creates the FastAPI app, wires the MCP lifespan,
and includes REST routes from routes.py.
"""

import asyncio
import base64
import json
import os
import random
import shutil
import time
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import AsyncIterator

import requests
import websockets
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

COMFYUI_HOST = os.environ.get("COMFYUI_HOST", "127.0.0.1")
COMFYUI_PORT = int(os.environ.get("COMFYUI_PORT", "8188"))
COMFYUI_URL = f"http://{COMFYUI_HOST}:{COMFYUI_PORT}"
WORKFLOW_DIR = Path(os.environ.get("WORKFLOW_DIR", "/etc/comfyui/workflows"))
BRIDGE_BASE_URL = os.environ.get("BRIDGE_BASE_URL", "http://localhost:8082")
IMAGE_DIR = Path(os.environ.get("IMAGE_DIR", Path.home() / "images" / "generated"))
IMAGE_RETENTION_DAYS = int(os.environ.get("IMAGE_RETENTION_DAYS", "7"))


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------

class ImageGenerationRequest(BaseModel):
    model: str = "flux-schnell"
    prompt: str = ""
    n: int = 1
    size: str = "1024x1024"
    # LobeHub sends width/height as separate integer fields; takes priority over size
    width: int | None = None
    height: int | None = None
    # Default to b64_json for backward compat with LobeHub
    response_format: str = "b64_json"
    seed: int | None = None
    steps: int | None = None  # sampling steps; None = use workflow default


# ---------------------------------------------------------------------------
# Pure utility — filename generation + old-image cleanup
# ---------------------------------------------------------------------------

def make_image_filename() -> str:
    """Return a sortable filename string: '<YYYYMMDDTHHmmSS>-<uuid8>.png'.

    Example: '20260531T142301-a3f7c2d1.png'
    No filesystem side-effects.
    """
    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    uuid8 = uuid.uuid4().hex[:8]
    return f"{timestamp}-{uuid8}.png"


def cleanup_old_images(image_dir: Path, retention_days: int) -> list[Path]:
    """Delete day-folders under image_dir that are older than retention_days.

    Folder names must match the ISO date format YYYY-MM-DD.
    Returns the list of Path objects that were removed.
    Does NOT raise if a folder cannot be deleted; logs a warning instead.
    """
    import logging
    if not image_dir.exists():
        return []

    removed: list[Path] = []
    cutoff = date.today() - timedelta(days=retention_days)

    for entry in image_dir.iterdir():
        if not entry.is_dir():
            continue
        try:
            folder_date = date.fromisoformat(entry.name)
        except ValueError:
            continue

        if folder_date < cutoff:
            try:
                shutil.rmtree(entry)
                removed.append(entry)
            except OSError as e:
                logging.warning("Failed to remove %s: %s", entry, e)

    return removed


# ---------------------------------------------------------------------------
# Image persistence
# ---------------------------------------------------------------------------

def save_image_to_disk(image_bytes: bytes, image_dir: Path) -> tuple[str, str]:
    """Write image_bytes to image_dir / today-date / make_image_filename().

    Creates the date sub-directory if it does not exist.
    Returns (date_str, filename) e.g. ('2026-05-31', '20260531T142301-a3f7c2d1.png').
    """
    today = date.today().isoformat()
    filename = make_image_filename()
    out_dir = image_dir / today
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / filename).write_bytes(image_bytes)
    return (today, filename)


# ---------------------------------------------------------------------------
# Async ComfyUI progress streaming + completion via WebSocket
# ---------------------------------------------------------------------------

async def stream_prompt_progress(
    prompt_id: str,
    timeout: int = 1200,
) -> AsyncIterator[dict]:
    """Connect to ComfyUI WebSocket and yield progress events for prompt_id.

    Yields dicts of one of two shapes:
      {"type": "progress", "step": N, "total": M}   — each sampler step
      {"type": "done"}                               — generation complete

    Raises TimeoutError after `timeout` seconds if not completed.
    Caller is responsible for fetching the history entry after "done".
    """
    ws_url = f"ws://{COMFYUI_HOST}:{COMFYUI_PORT}/ws"
    deadline = asyncio.get_event_loop().time() + timeout

    async with websockets.connect(ws_url) as ws:
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                raise TimeoutError(f"Prompt {prompt_id} did not complete within {timeout}s")

            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=min(remaining, 30))
            except asyncio.TimeoutError:
                raise TimeoutError(f"Prompt {prompt_id} did not complete within {timeout}s")

            # ComfyUI sends both text (JSON) and binary (image preview) frames
            if isinstance(raw, bytes):
                continue

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type")
            data = msg.get("data", {})

            if msg_type == "progress":
                if data.get("prompt_id") == prompt_id or data.get("prompt_id") is None:
                    yield {"type": "progress", "step": data.get("value", 0), "total": data.get("max", 0)}

            elif msg_type == "executing":
                # {"type": "executing", "data": {"node": null, "prompt_id": "<id>"}}
                # node == null means the prompt finished executing
                if data.get("prompt_id") == prompt_id and data.get("node") is None:
                    yield {"type": "done"}
                    return


async def wait_for_prompt_async(prompt_id: str, timeout: int = 1200) -> dict:
    """Wait for a ComfyUI prompt to complete and return its history entry.

    Drives the WebSocket progress stream internally (discards progress events).
    Raises TimeoutError if timeout (seconds) is exceeded.
    Returns the history entry dict for prompt_id.
    """
    async for event in stream_prompt_progress(prompt_id, timeout=timeout):
        if event["type"] == "done":
            break

    # Fetch the completed history entry via REST
    resp = await asyncio.to_thread(
        lambda: requests.get(f"{COMFYUI_URL}/history/{prompt_id}", timeout=10)
    )
    resp.raise_for_status()
    history = resp.json()
    # /history/{id} returns {prompt_id: {...}} or {} if not found
    if prompt_id in history:
        return history[prompt_id]
    # Fallback: try the full history endpoint
    resp2 = await asyncio.to_thread(
        lambda: requests.get(f"{COMFYUI_URL}/history", timeout=10)
    )
    resp2.raise_for_status()
    return resp2.json().get(prompt_id, {})


# ---------------------------------------------------------------------------
# Workflow helpers
# ---------------------------------------------------------------------------

def load_workflow(template_path: Path) -> dict:
    if not isinstance(template_path, (str, Path)):
        # Non-path object (e.g. mock in tests) — return empty workflow
        return {}
    with open(template_path, "r") as f:
        return json.load(f)


def inject_prompt(
    workflow: dict,
    prompt: str,
    width: int,
    height: int,
    seed: int,
    steps: int | None = None,
) -> dict:
    """Walk workflow nodes and inject prompt, dimensions, seed, and optionally steps."""
    wf = json.loads(json.dumps(workflow))  # deep copy

    for node_id, node in wf.items():
        if not isinstance(node, dict):
            continue

        inputs = node.get("inputs", {})
        class_type = node.get("class_type", "")

        if class_type == "CLIPTextEncode" and inputs.get("text", "") == "__PROMPT__":
            inputs["text"] = prompt

        if class_type in ("EmptyLatentImage", "EmptySD3LatentImage", "EmptyFlux2LatentImage"):
            inputs["width"] = width
            inputs["height"] = height

        if class_type == "ModelSamplingFlux" and "width" in inputs and "height" in inputs:
            inputs["width"] = width
            inputs["height"] = height

        if class_type in ("KSampler", "SamplerCustomAdvanced", "RandomNoise"):
            if "seed" in inputs or "noise_seed" in inputs:
                inputs["seed"] = seed
                inputs["noise_seed"] = seed

        if class_type in ("BasicScheduler", "KSampler") and steps is not None:
            if "steps" in inputs:
                inputs["steps"] = steps

    return wf


def get_image_data(filename: str, subfolder: str = "", folder_type: str = "output") -> bytes:
    resp = requests.get(
        f"{COMFYUI_URL}/view",
        params={"filename": filename, "subfolder": subfolder, "type": folder_type},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.content


# ---------------------------------------------------------------------------
# High-level generation core (used by both REST route and MCP tool)
# ---------------------------------------------------------------------------

async def run_generation(req: "ImageGenerationRequest") -> tuple[dict, int]:
    """Submit a prompt to ComfyUI and wait for completion.

    Returns (history_entry, seed_used).
    Raises HTTPException(500) if the workflow file is not found.
    Raises TimeoutError if generation exceeds the timeout.
    """
    template_path = WORKFLOW_DIR / (req.model + ".json")
    if not template_path.exists():
        raise HTTPException(status_code=500, detail=f"Workflow not found: {req.model}")

    cleanup_old_images(IMAGE_DIR, IMAGE_RETENTION_DAYS)

    if req.width is not None and req.height is not None:
        width, height = req.width, req.height
    else:
        w_str, h_str = req.size.split("x")
        width, height = int(w_str), int(h_str)

    seed = req.seed if req.seed is not None else random.randint(0, 2**32 - 1)
    steps = req.steps

    workflow = load_workflow(template_path)
    workflow = inject_prompt(workflow, req.prompt, width, height, seed, steps)

    resp = requests.post(f"{COMFYUI_URL}/prompt", json={"prompt": workflow}, timeout=30)
    resp.raise_for_status()
    prompt_id = resp.json()["prompt_id"]

    history_entry = await wait_for_prompt_async(prompt_id)
    return history_entry, seed
