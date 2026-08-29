#!/bin/bash
# Download the prebuilt q38rocm ROCmFPX engine (llama.cpp fork with ROCmFP4
# kernels, TurboQuant KV types and strict-Qwen MTP) for Strix Halo gfx1151.
#
# The binaries are dynamically linked against the ROCm userspace that is
# already present inside the kyuz0 rocm toolboxes — no host ROCm install
# needed. They run inside the container via LLAMA_SERVER_BIN override
# (default serving: systemd/llama-server@fork-router.service.d/override.conf
# + configs/fork-router.ini; single-lane via q38-llama wrapper).
#
# Usage: ./scripts/download-q38rocm-engine.sh [target-dir]
# Target: ~/opt/q38rocm (default)

set -e

TARGET_DIR="${1:-${HOME}/opt/q38rocm}"
ENGINE_URL="https://github.com/julianmb/q38rocm/releases/download/v1.5.2/strix-halo-rocmfpx-engine-v1.5.2-linux-x86_64.tar.gz"
SUMS_URL="https://raw.githubusercontent.com/julianmb/q38rocm/main/SHA256SUMS"
ARCHIVE="strix-halo-rocmfpx-engine-v1.5.2-linux-x86_64.tar.gz"

if [[ -x "$TARGET_DIR/engine/bin/llama-server" ]]; then
    echo "Engine already exists at $TARGET_DIR/engine/bin/llama-server"
    echo "Delete $TARGET_DIR first to re-download."
    exit 0
fi

echo "==> Downloading q38rocm engine to $TARGET_DIR"
mkdir -p "$TARGET_DIR"
curl -L --progress-bar "$ENGINE_URL" -o "$TARGET_DIR/$ARCHIVE"

# Best-effort integrity check against the upstream SHA256SUMS manifest.
if curl -fsSL "$SUMS_URL" -o "$TARGET_DIR/SHA256SUMS.upstream" 2>/dev/null; then
    if grep -q "$ARCHIVE" "$TARGET_DIR/SHA256SUMS.upstream"; then
        grep "$ARCHIVE" "$TARGET_DIR/SHA256SUMS.upstream" \
            | sed "s|[^ ]*|$TARGET_DIR/$ARCHIVE|" \
            | (cd / && sha256sum -c -) || {
                echo "Checksum mismatch! Removing broken download."
                rm -f "$TARGET_DIR/$ARCHIVE"
                exit 1
            }
    else
        echo "Note: archive not listed in upstream SHA256SUMS, skipping check."
    fi
else
    echo "Note: could not fetch upstream SHA256SUMS, skipping checksum."
fi

echo "==> Extracting"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
tar -xzf "$TARGET_DIR/$ARCHIVE" -C "$TMP_DIR"

BIN_SRC="$(dirname "$(find "$TMP_DIR" -type f -name llama-server | head -n1)")"
if [[ -z "$BIN_SRC" ]]; then
    echo "Error: llama-server not found inside archive."
    exit 1
fi
mkdir -p "$TARGET_DIR/engine/bin"
cp -a "$BIN_SRC"/. "$TARGET_DIR/engine/bin/"
rm -f "$TARGET_DIR/$ARCHIVE"

echo ""
echo "==> Done: $TARGET_DIR/engine/bin"
ls -la "$TARGET_DIR/engine/bin"
"$TARGET_DIR/engine/bin/llama-server" --version 2>/dev/null || true
