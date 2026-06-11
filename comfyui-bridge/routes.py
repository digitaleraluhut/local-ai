"""
FastAPI REST routes for the ComfyUI OpenAI bridge.
"""

import asyncio
import base64
import json
import random
import time

import requests
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

import bridge

router = APIRouter()


@router.get("/v1/images/{date}/{filename}")
async def serve_image(date: str, filename: str):
    """Serve a previously generated image as image/png.

    Path: IMAGE_DIR / date / filename
    Returns 404 if the file does not exist.
    """
    path = bridge.IMAGE_DIR / date / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(path, media_type="image/png")


@router.post("/v1/images/generations")
async def generate_images(req: bridge.ImageGenerationRequest, request: Request):
    """Generate image via ComfyUI.

    - Selects workflow from WORKFLOW_DIR/<model>.json
    - Cleans up day-folders older than IMAGE_RETENTION_DAYS
    - Saves image to IMAGE_DIR/YYYY-MM-DD/<timestamp>-<uuid8>.png
    - Returns b64_json (LobeHub compat) or {"url": "..."}

    When the client sends Accept: text/event-stream, streams SSE progress
    events while the sampler runs, then ends with the final result event.

    SSE event format:
      data: {"type": "progress", "step": N, "total": M}
      data: {"type": "result", "data": [...], "seed": N, "created": T}
      data: {"type": "error", "message": "..."}   (on failure)
    """
    template_path = bridge.WORKFLOW_DIR / (req.model + ".json")
    if not template_path.exists():
        raise HTTPException(status_code=500, detail=f"Workflow not found: {req.model}")

    bridge.cleanup_old_images(bridge.IMAGE_DIR, bridge.IMAGE_RETENTION_DAYS)

    # Resolve width/height
    if req.width is not None and req.height is not None:
        width, height = req.width, req.height
    else:
        w_str, h_str = req.size.split("x")
        width, height = int(w_str), int(h_str)

    seed = req.seed if req.seed is not None else random.randint(0, 2**32 - 1)
    steps = req.steps  # None = use workflow default

    workflow = bridge.load_workflow(template_path)
    workflow = bridge.inject_prompt(workflow, req.prompt, width, height, seed, steps)

    resp = requests.post(f"{bridge.COMFYUI_URL}/prompt", json={"prompt": workflow}, timeout=30)
    resp.raise_for_status()
    prompt_id = resp.json()["prompt_id"]

    accept = request.headers.get("accept", "")
    wants_sse = "text/event-stream" in accept

    if wants_sse:
        return StreamingResponse(
            _sse_generation_stream(prompt_id, req, seed),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    # Non-streaming path: wait for completion, then return JSON
    history_entry = await bridge.wait_for_prompt_async(prompt_id)
    images = await _collect_images(history_entry, req, seed)
    return JSONResponse({"data": images, "created": int(time.time()), "seed": seed})


async def _sse_generation_stream(prompt_id: str, req: bridge.ImageGenerationRequest, seed: int):
    """Async generator that yields SSE-formatted lines for a generation request."""
    try:
        async for event in bridge.stream_prompt_progress(prompt_id):
            if event["type"] == "progress":
                payload = json.dumps({"type": "progress", "step": event["step"], "total": event["total"]})
                yield f"data: {payload}\n\n"
            elif event["type"] == "done":
                break

        # Generation complete — fetch history and return result
        resp = await asyncio.to_thread(
            lambda: requests.get(f"{bridge.COMFYUI_URL}/history/{prompt_id}", timeout=10)
        )
        resp.raise_for_status()
        history = resp.json()
        history_entry = history.get(prompt_id, {})

        images = await _collect_images(history_entry, req, seed)
        result_payload = json.dumps({"type": "result", "data": images, "seed": seed, "created": int(time.time())})
        yield f"data: {result_payload}\n\n"
    except Exception as exc:
        error_payload = json.dumps({"type": "error", "message": str(exc)})
        yield f"data: {error_payload}\n\n"


async def _collect_images(history_entry: dict, req: bridge.ImageGenerationRequest, seed: int) -> list:
    """Extract, fetch, persist and format images from a ComfyUI history entry."""
    images = []
    for node_output in history_entry.get("outputs", {}).values():
        for img_info in node_output.get("images", []):
            image_bytes = bridge.get_image_data(
                img_info["filename"],
                img_info.get("subfolder", ""),
                img_info.get("type", "output"),
            )
            date_str, filename = bridge.save_image_to_disk(image_bytes, bridge.IMAGE_DIR)

            if req.response_format == "b64_json":
                images.append({"b64_json": base64.b64encode(image_bytes).decode("utf-8")})
            else:
                images.append({"url": f"{bridge.BRIDGE_BASE_URL}/v1/images/{date_str}/{filename}"})
    return images


@router.get("/v1/models")
def list_models():
    workflow_dir = bridge.WORKFLOW_DIR
    models = []
    if workflow_dir.is_dir():
        for p in sorted(workflow_dir.glob("*.json")):
            models.append({"id": p.stem, "object": "model"})
    if not models:
        models = [
            {"id": "flux-dev", "object": "model"},
            {"id": "flux-dev-fast", "object": "model"},
            {"id": "flux-dev-3-2", "object": "model"},
            {"id": "flux-dev-2-3", "object": "model"},
        ]
    return JSONResponse(content={"object": "list", "data": models})


@router.get("/health")
def health():
    try:
        resp = requests.get(f"{bridge.COMFYUI_URL}/system_stats", timeout=5)
        if resp.status_code == 200:
            return {"status": "ok", "comfyui": "ready"}
    except Exception:
        pass
    return {"status": "degraded", "comfyui": "unreachable"}
