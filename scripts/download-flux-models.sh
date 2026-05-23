#!/bin/bash
# Download FLUX dev GGUF models and required components.
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
# FLUX.1-dev Q4_K_S GGUF (non-commercial license, personal use only)
download \
    "https://huggingface.co/city96/FLUX.1-dev-gguf/resolve/main/flux1-dev-Q4_K_S.gguf" \
    "$MODELS_DIR/unet/flux1-dev-Q4_K_S.gguf"

echo ""
echo "==> Text Encoders"
# T5-XXL encoder (standard fp16 safetensors — ComfyUI loads this via DualCLIPLoader)
download \
    "https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/t5xxl_fp16.safetensors" \
    "$MODELS_DIR/clip/t5xxl_fp16.safetensors"

# CLIP-L encoder
download \
    "https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/clip_l.safetensors" \
    "$MODELS_DIR/clip/clip_l.safetensors"

echo ""
echo "==> VAE"
# FLUX VAE (Comfy-Org repackaged, public access)
download \
    "https://huggingface.co/Comfy-Org/Lumina_Image_2.0_Repackaged/resolve/main/split_files/vae/ae.safetensors" \
    "$MODELS_DIR/vae/ae.safetensors"

echo ""
echo "==> Download complete!"
echo ""
echo "Model files:"
find "$MODELS_DIR" -type f | sort
echo ""
echo "Total size:"
du -sh "$MODELS_DIR"
