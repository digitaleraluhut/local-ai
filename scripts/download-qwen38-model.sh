#!/bin/bash
# Download the Qwen3.8-27B ROCmFP4_FAST GGUF (13.55 GiB) for the
# julianmb/q38rocm engine (preset configs/qwen3.8-27b-fp4.ini, launched
# via ./q38-llama).
#
# Usage: ./scripts/download-qwen38-model.sh [target-dir]
# Target: ~/models/qwen3.8-27b (default)

set -e

TARGET_DIR="${1:-${HOME}/models/qwen3.8-27b}"
FP4_URL="https://huggingface.co/julianmb/Qwen-3.8-27B-ROCmFP4-FAST-GGUF/resolve/main"

echo "==> Downloading Qwen3.8-27B models to $TARGET_DIR"
mkdir -p "$TARGET_DIR"

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

verify_sha256() {
    local file="$1"
    local expected="$2"
    echo "  Verifying SHA256 of $(basename "$file")..."
    if ! echo "${expected}  ${file}" | sha256sum -c - >/dev/null 2>&1; then
        echo "  ERROR: checksum mismatch! Delete the file and retry."
        exit 1
    fi
    echo "  OK"
}

# ROCmFP4_FAST — custom 4.26 bpw layout, requires the q38rocm engine fork
# (stock llama.cpp cannot load it). SHA256 from the upstream README.
download \
    "${FP4_URL}/Qwen3.8-27B-ROCmFP4-FAST.gguf" \
    "$TARGET_DIR/Qwen3.8-27B-ROCmFP4-FAST.gguf"
verify_sha256 \
    "$TARGET_DIR/Qwen3.8-27B-ROCmFP4-FAST.gguf" \
    "fb89c78d2be91cdb68eaaaa45b1270710bf34aa721dc1f0b9e3aa7b98d2e1da9"

echo ""
echo "==> Download complete!"
echo ""
echo "Model files:"
find "$TARGET_DIR" -type f -name "*.gguf" | sort
echo ""
echo "Total size:"
du -sh "$TARGET_DIR"
