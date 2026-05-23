#!/bin/bash
# One-shot setup script for ComfyUI inside a distrobox container.
# Installs ComfyUI, ComfyUI-GGUF custom node, and bridge dependencies.
#
# Usage: ./scripts/setup-comfyui-container.sh [container-name]
#   Defaults to: comfyui-rocm

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
CONTAINER_NAME="${1:-comfyui-rocm}"

echo "==> Setting up ComfyUI in distrobox container: $CONTAINER_NAME"

# Check container exists
if ! distrobox list | grep -q "^.*| $CONTAINER_NAME |"; then
    echo "Error: Container $CONTAINER_NAME not found."
    echo "Create it first by running: ./comfyui-server flux-schnell"
    echo "(This will auto-create the container from the kyuz0 ROCm image.)"
    exit 1
fi

# Install dependencies inside container
distrobox enter "$CONTAINER_NAME" -- bash -c '
set -e

echo "==> Installing system dependencies..."
sudo dnf install -y git python3-pip python3-venv cmake gcc-c++ ninja-build

echo "==> Installing PyTorch for ROCm..."
pip3 install --upgrade torch torchvision torchaudio --index-url https://download.pytorch.org/whl/rocm6.2

echo "==> Cloning ComfyUI..."
if [[ -d ~/ComfyUI ]]; then
    echo "ComfyUI already exists, updating..."
    cd ~/ComfyUI
    git pull
else
    git clone https://github.com/comfyanonymous/ComfyUI.git ~/ComfyUI
fi

echo "==> Installing ComfyUI dependencies..."
cd ~/ComfyUI
pip3 install -r requirements.txt

echo "==> Installing ComfyUI-GGUF custom node..."
CUSTOM_NODES_DIR="~/ComfyUI/custom_nodes"
mkdir -p "$CUSTOM_NODES_DIR"

if [[ -d "$CUSTOM_NODES_DIR/ComfyUI-GGUF" ]]; then
    echo "ComfyUI-GGUF already exists, updating..."
    cd "$CUSTOM_NODES_DIR/ComfyUI-GGUF"
    git pull
else
    git clone https://github.com/city96/ComfyUI-GGUF.git "$CUSTOM_NODES_DIR/ComfyUI-GGUF"
fi

pip3 install --upgrade gguf

echo "==> Installing bridge dependencies..."
pip3 install fastapi uvicorn requests python-multipart

echo ""
echo "==> Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Run ./scripts/download-flux-models.sh to download model files"
echo "  2. Start the server: systemctl --user enable --now comfyui-server@flux-schnell"
'
