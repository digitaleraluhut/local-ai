#!/bin/bash
# Download a Whisper model in GGML format.
#
# Usage: download-whisper-model.sh [model-name] [target-dir]
#
# Models: tiny, base, small, medium, large-v1, large-v2, large-v3, large-v3-turbo
# Default: small (good balance for dev/testing)
# Target:  ~/models/whisper (default)

set -e

MODEL="${1:-small}"
TARGET_DIR="${2:-/home/jaegle/models/whisper}"

# whisper.cpp model download base URL
BASE_URL="https://huggingface.co/ggerganov/whisper.cpp/resolve/main"

echo "==> Downloading whisper model: $MODEL"
echo "    Target: $TARGET_DIR"
echo ""

mkdir -p "$TARGET_DIR"

# Map model name to filename
case "$MODEL" in
    tiny)       FILE="ggml-tiny.bin" ;;
    tiny.en)    FILE="ggml-tiny.en.bin" ;;
    base)       FILE="ggml-base.bin" ;;
    base.en)    FILE="ggml-base.en.bin" ;;
    small)      FILE="ggml-small.bin" ;;
    small.en)   FILE="ggml-small.en.bin" ;;
    medium)     FILE="ggml-medium.bin" ;;
    medium.en)  FILE="ggml-medium.en.bin" ;;
    large-v1)   FILE="ggml-large-v1.bin" ;;
    large-v2)   FILE="ggml-large-v2.bin" ;;
    large-v3)   FILE="ggml-large-v3.bin" ;;
    large-v3-turbo) FILE="ggml-large-v3-turbo.bin" ;;
    *)
        echo "Error: unknown model '$MODEL'"
        echo "Available: tiny, tiny.en, base, base.en, small, small.en, medium, medium.en, large-v1, large-v2, large-v3, large-v3-turbo"
        exit 1
        ;;
esac

if [[ -f "$TARGET_DIR/$FILE" ]]; then
    echo "Model already exists at $TARGET_DIR/$FILE"
    echo "Delete it first to re-download."
else
    echo "Downloading $FILE..."
    curl -L "$BASE_URL/$FILE" -o "$TARGET_DIR/$FILE"
    echo ""
    echo "Done: $TARGET_DIR/$FILE ($(du -h "$TARGET_DIR/$FILE" | cut -f1))"
fi
