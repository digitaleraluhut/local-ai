#!/usr/bin/env python3
"""
OpenAI-compatible API bridge for ComfyUI.
Translates POST /v1/images/generations into ComfyUI workflow execution.

Environment variables:
  WORKFLOW_FILE   - Path to the workflow JSON template to use
  COMFYUI_HOST    - ComfyUI host (default: 127.0.0.1)
  COMFYUI_PORT    - ComfyUI port (default: 8188)
  BRIDGE_PORT     - Port for this bridge (default: 8082)

Response format:
  The bridge always fetches image bytes from ComfyUI internally after generation.
  Default response_format is "b64_json" — the image data is already in memory, so
  returning it inline avoids exposing a ComfyUI-internal URL (127.0.0.1:8188) to
  callers that cannot reach ComfyUI directly (e.g. a pod in another k8s namespace).
  Pass response_format="url" only when the caller can reach COMFYUI_HOST directly.
"""

import json
import os
import random
import time
import base64
from pathlib import Path

import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

app = FastAPI(title="ComfyUI OpenAI Bridge")

COMFYUI_HOST = os.environ.get("COMFYUI_HOST", "127.0.0.1")
COMFYUI_PORT = int(os.environ.get("COMFYUI_PORT", "8188"))
COMFYUI_URL = f"http://{COMFYUI_HOST}:{COMFYUI_PORT}"
WORKFLOW_FILE = os.environ.get("WORKFLOW_FILE", "")


class ImageGenerationRequest(BaseModel):
    model: str = "flux-schnell"
    prompt: str = ""
    n: int = 1
    size: str = "1024x1024"
    # Default to b64_json: the bridge fetches image bytes from ComfyUI internally anyway,
    # so returning them inline avoids leaking a 127.0.0.1 URL that remote callers can't reach.
    response_format: str = "b64_json"
    seed: int | None = None


def load_workflow(template_path: str) -> dict:
    with open(template_path, "r") as f:
        return json.load(f)


def inject_prompt(workflow: dict, prompt: str, width: int, height: int, seed: int) -> dict:
    """Walk workflow nodes and inject prompt, dimensions, and seed."""
    wf = json.loads(json.dumps(workflow))  # deep copy

    for node_id, node in wf.items():
        if not isinstance(node, dict):
            continue

        inputs = node.get("inputs", {})
        class_type = node.get("class_type", "")

        # Inject positive prompt
        if class_type == "CLIPTextEncode" and inputs.get("text", "") == "__PROMPT__":
            inputs["text"] = prompt

        # Inject dimensions into latent image node
        if class_type in ("EmptyLatentImage", "EmptySD3LatentImage", "EmptyFlux2LatentImage"):
            inputs["width"] = width
            inputs["height"] = height

        # Inject seed into sampler
        if class_type in ("KSampler", "SamplerCustomAdvanced", "RandomNoise"):
            if "seed" in inputs or "noise_seed" in inputs:
                inputs["seed"] = seed
                inputs["noise_seed"] = seed

    return wf


def wait_for_prompt(prompt_id: str, timeout: int = 1200) -> dict:
    """Poll ComfyUI /history until our prompt is complete."""
    start = time.time()
    while time.time() - start < timeout:
        resp = requests.get(f"{COMFYUI_URL}/history", timeout=10)
        resp.raise_for_status()
        history = resp.json()
        if prompt_id in history:
            return history[prompt_id]
        time.sleep(0.5)
    raise TimeoutError(f"Prompt {prompt_id} did not complete within {timeout}s")


def get_image_data(filename: str, subfolder: str = "", folder_type: str = "output") -> bytes:
    resp = requests.get(
        f"{COMFYUI_URL}/view",
        params={"filename": filename, "subfolder": subfolder, "type": folder_type},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.content


@app.post("/v1/images/generations")
def generate_images(req: ImageGenerationRequest):
    if not WORKFLOW_FILE:
        raise HTTPException(status_code=500, detail="WORKFLOW_FILE not set")

    # Parse size
    try:
        width, height = map(int, req.size.split("x"))
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid size format: {req.size}")

    seed = req.seed if req.seed is not None else random.randint(0, 2**32 - 1)

    workflow = load_workflow(WORKFLOW_FILE)
    workflow = inject_prompt(workflow, req.prompt, width, height, seed)

    # Submit to ComfyUI
    payload = {"prompt": workflow, "client_id": "comfyui-bridge"}
    resp = requests.post(f"{COMFYUI_URL}/prompt", json=payload, timeout=30)
    if resp.status_code != 200:
        raise HTTPException(status_code=500, detail=f"ComfyUI error: {resp.text}")

    prompt_id = resp.json().get("prompt_id")
    if not prompt_id:
        raise HTTPException(status_code=500, detail="No prompt_id from ComfyUI")

    # Wait for completion
    try:
        history = wait_for_prompt(prompt_id)
    except TimeoutError as e:
        raise HTTPException(status_code=504, detail=str(e))

    # Extract output images
    outputs = history.get("outputs", {})
    images = []
    for node_id, node_output in outputs.items():
        if "images" in node_output:
            for img in node_output["images"]:
                filename = img["filename"]
                subfolder = img.get("subfolder", "")
                folder_type = img.get("type", "output")

                image_data = get_image_data(filename, subfolder, folder_type)

                if req.response_format == "b64_json":
                    b64 = base64.b64encode(image_data).decode("utf-8")
                    images.append({"b64_json": b64})
                else:
                    # Return a local URL pointing to ComfyUI's view endpoint
                    url = f"{COMFYUI_URL}/view?filename={filename}"
                    if subfolder:
                        url += f"&subfolder={subfolder}"
                    url += f"&type={folder_type}"
                    images.append({"url": url})

    return JSONResponse(content={"data": images, "created": int(time.time())})


@app.get("/v1/models")
def list_models():
    # Return the available workflow presets
    return JSONResponse(
        content={
            "object": "list",
            "data": [
                {"id": "flux-dev", "object": "model"},
                {"id": "flux-dev-fast", "object": "model"},
                {"id": "flux-dev-3-2", "object": "model"},
                {"id": "flux-dev-2-3", "object": "model"},
            ],
        }
    )


@app.get("/health")
def health():
    try:
        resp = requests.get(f"{COMFYUI_URL}/system_stats", timeout=5)
        if resp.status_code == 200:
            return {"status": "ok", "comfyui": "ready"}
    except Exception:
        pass
    return {"status": "degraded", "comfyui": "unreachable"}


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("BRIDGE_PORT", "8082"))
    uvicorn.run(app, host="0.0.0.0", port=port)
