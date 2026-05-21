#!/bin/bash
# Build the custom ROCm llama.cpp + whisper.cpp container image
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

IMAGE_NAME="${1:-rocm-llama-whisper}"
IMAGE_TAG="${2:-latest}"
CONTAINER_NAME="${3:-rocm-llama-whisper}"

echo "==> Building container image: $IMAGE_NAME:$IMAGE_TAG"
podman build -t "$IMAGE_NAME:$IMAGE_TAG" \
    -f "$REPO_DIR/container/Containerfile.rocm-whisper" \
    "$REPO_DIR"

echo ""
echo "==> Build complete."
echo ""
echo "To create a distrobox from this image, run:"
echo ""
echo "  distrobox create -n $CONTAINER_NAME \\"
echo "    --image localhost/$IMAGE_NAME:$IMAGE_TAG \\"
echo "    --additional-flags \"--device /dev/kfd --device /dev/dri \\"
echo "      --group-add video --group-add render \\"
echo "      --security-opt seccomp=unconfined\""
echo ""
echo "  distrobox enter $CONTAINER_NAME"
echo ""
echo "To update an existing container to use the new image:"
echo ""
echo "  distrobox stop $CONTAINER_NAME"
echo "  distrobox rm $CONTAINER_NAME"
echo "  distrobox create ... (as above)"
