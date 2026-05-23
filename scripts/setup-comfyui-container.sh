#!/bin/bash
# One-shot setup script for ComfyUI inside a distrobox container.
# Installs ComfyUI, ComfyUI-GGUF custom node, and bridge dependencies.
#
# Usage: ./scripts/setup-comfyui-container.sh [container-name]
#   Defaults to: comfyui-rocm
#
# NOTE: The AMD PyTorch+ROCm base image installs PyTorch in a root-owned venv
# at /opt/venv. We use PYTHONPATH to make it available and --break-system-packages
# to install ComfyUI deps into the system Python.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONTAINER_NAME="${1:-comfyui-rocm}"

echo "==> Setting up ComfyUI in distrobox container: $CONTAINER_NAME"

# Check container exists
if ! distrobox list | grep -q "| $CONTAINER_NAME"; then
    echo "Error: Container $CONTAINER_NAME not found."
    echo "Create it first by running: ./comfyui-server flux-schnell"
    echo "(This will auto-create the container from the AMD PyTorch+ROCm image.)"
    exit 1
fi

# Write setup script to a temp file and copy into container
TMP_SCRIPT="/tmp/setup-comfyui-$$.sh"
cat > "$TMP_SCRIPT" << 'EOF'
#!/bin/bash
set -e

# Add the pre-installed PyTorch+ROCm venv to PYTHONPATH
VENV_SITE="/opt/venv/lib/python3.12/site-packages"
export PYTHONPATH="${VENV_SITE}:${PYTHONPATH}"

echo "==> Verifying PyTorch+ROCm..."
python3 -c 'import torch; print("PyTorch version:", torch.__version__); print("CUDA/ROCm available:", torch.cuda.is_available())'

echo "==> Installing system dependencies..."
sudo apt-get update
sudo apt-get install -y git cmake build-essential ninja-build

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
pip3 install --break-system-packages -r requirements.txt

echo "==> Installing ComfyUI-GGUF custom node..."
CUSTOM_NODES_DIR="${HOME}/ComfyUI/custom_nodes"
mkdir -p "$CUSTOM_NODES_DIR"

if [[ -d "$CUSTOM_NODES_DIR/ComfyUI-GGUF" ]]; then
    echo "ComfyUI-GGUF already exists, updating..."
    cd "$CUSTOM_NODES_DIR/ComfyUI-GGUF"
    git pull
else
    git clone https://github.com/city96/ComfyUI-GGUF.git "$CUSTOM_NODES_DIR/ComfyUI-GGUF"
fi

pip3 install --break-system-packages --upgrade gguf

echo "==> Installing bridge dependencies..."
pip3 install --break-system-packages fastapi uvicorn requests python-multipart

echo ""
echo "==> Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Run ./scripts/download-flux-models.sh to download model files"
echo "  2. Start the server: systemctl --user enable --now comfyui-server@flux-schnell"
EOF

# Copy and execute inside container
podman cp "$TMP_SCRIPT" "$CONTAINER_NAME:/tmp/setup-comfyui.sh"
distribox enter "$CONTAINER_NAME" -- bash /tmp/setup-comfyui.sh
rm -f "$TMP_SCRIPT"
