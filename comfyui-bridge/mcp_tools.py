"""
MCP tool definition for the ComfyUI image generation bridge.
"""

import base64
from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

import bridge
from bridge import ImageGenerationRequest

mcp = FastMCP("comfyui-image-tool")


class ImageGenerationResult(BaseModel):
    """Structured result returned by the generate_image MCP tool."""

    url: str
    seed: int


ModelChoice = Literal[
    "flux-dev",
    "flux-dev-fast",
]


@mcp.tool()
async def generate_image(
    prompt: Annotated[
        str,
        Field(description="Detailed text description of the image to generate"),
    ],
    model: Annotated[
        ModelChoice,
        Field(
            description=(
                "Workflow preset to use. "
                "flux-dev: best quality, ~2-3 min. "
                "flux-dev-fast: good quality, ~1 min."
            ),
        ),
    ] = "flux-dev-fast",
    width: Annotated[
        int,
        Field(
            description="Image width in pixels (default: 1024). Must be a multiple of 8.",
            ge=64,
            le=2048,
        ),
    ] = 1024,
    height: Annotated[
        int,
        Field(
            description="Image height in pixels (default: 1024). Must be a multiple of 8.",
            ge=64,
            le=2048,
        ),
    ] = 1024,
    steps: Annotated[
        int | None,
        Field(
            description=(
                "Number of diffusion sampling steps (default: 20). "
                "Higher values improve detail and coherence at the cost of generation time. "
                "flux-dev: 20–30 for best quality. flux-dev-fast: 8–12 for speed. "
                "Range: 1–150."
            ),
            ge=1,
            le=150,
        ),
    ] = None,
    seed: Annotated[
        int | None,
        Field(
            description=(
                "Noise seed for reproducibility (integer, e.g. 1744492399). "
                "Omit or pass null to use a random seed — the used seed is always returned. "
                "Re-use a seed from a previous result to keep the same motif, composition, "
                "and lighting while changing prompt, model, width, or height."
            ),
        ),
    ] = None,
) -> ImageGenerationResult:
    """Generate an image from a text prompt using the local FLUX model.

    Always save the returned seed. Re-use it with different width, height, steps, or
    model to reproduce the same motif at higher quality or a different aspect ratio.
    For best quality use flux-dev with steps=25-30. For speed use flux-dev-fast with
    steps=12-20.
    """
    try:
        req = ImageGenerationRequest(
            prompt=prompt,
            model=model,
            width=width,
            height=height,
            steps=steps,
            seed=seed,
            response_format="url",
        )
        history_entry, used_seed = await bridge.run_generation(req)
        # Collect image URLs from the history entry
        for node_output in history_entry.get("outputs", {}).values():
            for img_info in node_output.get("images", []):
                image_bytes = bridge.get_image_data(
                    img_info["filename"],
                    img_info.get("subfolder", ""),
                    img_info.get("type", "output"),
                )
                date_str, filename = bridge.save_image_to_disk(image_bytes, bridge.IMAGE_DIR)
                url = f"{bridge.BRIDGE_BASE_URL}/v1/images/{date_str}/{filename}"
                return ImageGenerationResult(url=url, seed=used_seed)
        raise RuntimeError("ComfyUI returned no images")
    except Exception as e:
        raise RuntimeError(str(e)) from e
