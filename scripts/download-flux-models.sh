#!/bin/bash
# Download FLUX schnell GGUF models and required components.
# Places files in ~/models/comfyui/ following ComfyUI conventions.
#
# Usage: ./scripts/download-flux-models.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODELS_DIR="${HOME}/models/comfyui"

echo "==> Downloading FLUX models to $MODELS_DIR"
mkdir -p "$MODELS_DIR"/{unet,clip,vae}

# Helper to download with progress
download() {
    local url="$1"
    local dest="$2"
    if [[ -f "$dest" ]]; then
        echo "  Already exists: $(basename "$dest")"
        return 0
    fi
    echo "  Downloading: $(basename "$dest")"
    curl -L --progress-bar "$url" -o "$dest"
}

echo ""
echo "==> UNet (Diffusion Model)"
# FLUX.1-schnell Q4_K_S GGUF
download \
    "https://huggingface.co/city96/FLUX.1-schnell-gguf/resolve/main/flux1-schnell-Q4_K_S.gguf" \
    "$MODELS_DIR/unet/flux1-schnell-Q4_K_S.gguf"

echo ""
echo "==> Text Encoders"
# T5-XXL encoder (standard fp16 safetensors — ComfyUI loads this via DualCLIPLoader)
# If you want the quantized GGUF version instead, use city96/t5-v1_1-xxl-encoder-gguf
download \
    "https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/t5xxl_fp16.safetensors" \
    "$MODELS_DIR/clip/t5xxl_fp16.safetensors"

# CLIP-L encoder
download \
    "https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/clip_l.safetensors" \
    "$MODELS_DIR/clip/clip_l.safetensors"

# Optional: T5-XXL GGUF (uncomment to use quantized T5 instead of fp16)
# download \
#     "https://huggingface.co/city96/t5-v1_1-xxl-encoder-gguf/resolve/main/t5-v1_1-xxl-encoder-Q4_K_S.gguf" \
#     "$MODELS_DIR/clip/t5-v1_1-xxl-encoder-Q4_K_S.gguf"

echo ""
echo "==> VAE"
# FLUX VAE
download \
    "https://huggingface.co/black-forest-labs/FLUX.1-schnell/resolve/main/ae.safetensors" \
    "$MODELS_DIR/vae/ae.safetensors"

echo ""
echo "==> Download complete!"
echo ""
echo "Model files:"
find "$MODELS_DIR" -type f | sort
echo ""
echo "Total size:"
du -sh "$MODELS_DIR"
