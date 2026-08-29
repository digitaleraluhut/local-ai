# Local LLM Server - Easy Model Experiments with llama.cpp

> Part of [digitaleraluhut](https://github.com/digitaleraluhut) — the AI layer. Provides LLM, STT, and image generation endpoints consumed by apps in [homelab-apps](https://github.com/digitaleraluhut/homelab-apps) (e.g. LobeHub, Matrix transcription bot). Runs on the same machine as the [homelab](https://github.com/digitaleraluhut/homelab) cluster.

This repository makes it easy to launch and experiment with different LLM models in [llama.cpp](https://github.com/ggml-org/llama.cpp) across different GPU backends (ROCm, Vulkan), with support for saving experiment configurations for reproducibility.

## Overview

The goal is to provide a simple, reproducible way to:
- Launch llama.cpp models with pre-configured settings
- Experiment with different models, context sizes, batch sizes, and optimization flags
- Save working configurations for future reference
- Support multiple GPU backends via containerized environments

The core philosophy: **every model is a preset file**. Servers run one preset
(or several, in router mode), model paths stay portable via `$MODELS_DIR`, and
"switching models" is just enabling a different preset — not editing code or
binaries. See "Configuration" and "Available Presets".

## Security & Sensitive Data

Model paths are kept out of the repo. All `configs/*.ini` files use `/path/to/models/` as a placeholder. At launch, `llama-server-container` substitutes it with `$MODELS_DIR` before passing the preset to llama-server — the original files are never modified.

### Local setup on a new machine

```bash
git clone https://github.com/digitaleraluhut/local-ai.git
cd local-ai

# Point to your model directory (default: ~/models)
export MODELS_DIR=~/models   # add to ~/.bashrc to make permanent

# Launch a model
rocm-llama qwen3-coder-30b
```

## Prerequisites

### Ubuntu + Distrobox

This setup uses [distrobox](https://distrobox.it/) to run containerized GPU toolchains. This is necessary on Ubuntu because the containerized environments from [kyuz0/amd-strix-halo-toolboxes](https://github.com/kyuz0/amd-strix-halo-toolboxes) don't work natively with Ubuntu's default container setup. See [this issue](https://github.com/kyuz0/amd-strix-halo-toolboxes/issues/16) for details.

**Install distrobox:**
```bash
curl -s https://raw.githubusercontent.com/89luca89/distrobox/main/install | sudo sh
```

> **Version requirement:** distrobox **≥ 1.8.2** is required for the current
> toolboxes (Fedora 44 base). Older releases (e.g. Ubuntu 24.04's 1.7.0) fail
> during container init with `chpasswd: invalid password hash`. On Ubuntu
> 24.04, upgrade by installing the newer `.deb` from the Ubuntu archive:
> ```bash
> curl -sLO http://archive.ubuntu.com/ubuntu/pool/universe/d/distrobox/distrobox_1.8.2.5-1_all.deb
> sudo apt install ./distrobox_1.8.2.5-1_all.deb
> ```
> Verify with `distrobox --version`.

### Container Images

This project uses the amazing [kyuz0/amd-strix-halo-toolboxes](https://github.com/kyuz0/amd-strix-halo-toolboxes) which provides pre-built containerized environments for different GPU backends:

- **ROCm 7.14**: `docker.io/kyuz0/amd-strix-halo-toolboxes:rocm-7.14` (default)
- **Vulkan RADV**: `docker.io/kyuz0/amd-strix-halo-toolboxes:vulkan-radv`

These containers handle all GPU driver setup automatically.

## Quick Start

### Launch a Model

```bash
# ROCm backend
rocm-llama qwen3-coder-30b --port 8000

# Vulkan backend
vulkan-llama devstral-small-24b --port 8080

# View available models
rocm-llama
```

### Access the Server

Once running, the server is available at:
- Localhost: `http://localhost:8000`
- Network: `http://<your-machine-ip>:8000`

## Configuration

Every preset is an `.ini` file in `./configs/` handed to
`llama-server --models-preset` (router mode). A preset holds one or several
models; the section header (`[qwen...]`) is the alias used in the OpenAI
`model` field. Launch any preset by basename:

```bash
rocm-llama <preset-name>                # ROCm backend (this host)
vulkan-llama <preset-name>              # Vulkan backend
rocm-llama                              # list available presets
```

Three presets worth knowing first:

- **`configs/fork-router.ini`** — the active default on this host:
  qwen3.8-27b-fp4 (strict MTP + prompt caching, ~28 tok/s) plus bge-m3
  embeddings, all from one q38rocm fork engine. See "Qwen3.8-27B".
- **`configs/router.ini`** — multi-model stock preset: on-demand loading +
  LRU eviction with bge-m3 warm. The pre-fork reference.
- **`configs/qwen3-coder-30b.ini`** — the smallest single-model preset;
  copy this shape when adding a model. The purpose of every preset is in
  "Available Presets" below.

INI keys are llama-server CLI flag names without the leading dashes
(`--n-gpu-layers` → `ngl`); booleans are `true`/`false`. Settings under `[*]`
apply to every section in the file (and to any cached HF models). Two
preset-only keys: `load-on-startup = true` (eager-load on server start)
and `stop-timeout = N` (seconds to wait for graceful unload). Most
hand-picked settings in the shipped files explain their measured effect in
comments — open them instead of trusting this summary.

### Environment Variables

```bash
# Path to your local model files — substituted into all .ini presets at launch.
# Defaults to ~/models if unset.
export MODELS_DIR=~/models

# Use custom preset directory
LLAMA_CONFIG_DIR=~/.config/model-configs rocm-llama qwen3-coder-30b --port 8000

# Or set permanently
export LLAMA_CONFIG_DIR=~/.config/model-configs
```

Model paths in `configs/*.ini` use `/path/to/models/` as a placeholder. At launch, `llama-server-container` replaces that prefix with `$MODELS_DIR` in a temporary copy of the preset before passing it to llama-server. The original `.ini` files are never modified.

## Script Architecture

### Host-side (Entry Points)

- **`rocm-llama`** — wrapper → `llama-server rocm`
- **`vulkan-llama`** — wrapper → `llama-server vulkan`
- **`llama-server`** — orchestrator that creates the distrobox container
  on first use, copies presets and the wrapper into it, then enters the
  container

### Container-side

- **`llama-server-container`** — resolves `/path/to/models` to `$MODELS_DIR`
  in a temp copy, then exec's `llama-server --models-preset <preset>.ini`.
  llama.cpp parses the INI directly — no flag translation. On-demand
  autoload (LRU at `models-max`) is upstream-default; per-instance opt-out
  with `LLAMA_NO_AUTOLOAD=1` (adds `--no-models-autoload`).

## Adding a New Model

Start from the example shape (`configs/qwen3-coder-30b.ini`), drop the
copy in `./configs/`, and launch it by basename:

```bash
cp ./configs/qwen3-coder-30b.ini ./configs/my-model.ini
# edit: [my-model] header, model = /path/to/models/.../gguf, c = <ctx>, load-on-startup
rocm-llama my-model --port 8000
```

If the distrobox container already exists, copy the file into the
container's view (host `$HOME` is shared, so this is just a `cp`):

```bash
cp ./configs/my-model.ini ~/.config/llama-cpp/
```

To share it across requests on-demand instead, add the section to an
existing router preset (`configs/router.ini`) — it becomes another model
alias on that instance.

## Speech-to-Text (STT) — whisper.cpp

This setup extends llama.cpp with speech-to-text via [whisper.cpp](https://github.com/ggml-org/whisper.cpp),
built with ROCm/HIP acceleration on the same Strix Halo GPU.

STT runs as a **separate server** on its own port (default `8081`), not
inside the llama.cpp router. whisper.cpp is a different binary with a
custom `/inference` endpoint.

### Container Image

whisper.cpp is not in the upstream kyuz0 image. A custom image is defined
in `container/Containerfile.rocm-whisper`:

```bash
# Build the image (one-time)
./scripts/build-whisper-image.sh

# Create the distrobox
distrobox create -n rocm-llama-whisper \
  --image localhost/rocm-llama-whisper:latest \
  --additional-flags "--device /dev/kfd --device /dev/dri \
    --group-add video --group-add render \
    --security-opt seccomp=unconfined"
```

The Containerfile extends kyuz0's ROCm 7.2 image (which has llama.cpp) and
adds `whisper-server` on top — the resulting image contains both runtimes.

### Model Download

Download a Whisper model in GGML format:

```bash
# Download small model (~466 MB, good for testing / dev)
./scripts/download-whisper-model.sh small

# Or a larger model for production quality
./scripts/download-whisper-model.sh large-v3-turbo
```

| Model | Size | Use case |
|---|---|---|
| `tiny` | ~39 MB | Fastest, lowest quality |
| `base` | ~74 MB | Fast, acceptable quality |
| `small` | ~466 MB | **Default — good balance** |
| `medium` | ~1.5 GB | High quality, slower |
| `large-v3-turbo` | ~1.6 GB | Best quality, slowest load |

Models are cached in `~/models/whisper/` by default.

### Configuration

`configs/whisper.ini` holds the default preset (`[stt-default]`): model
`small` (German), 4 threads, VAD off, port 8081. Read it before tuning
anything. New presets follow the same pattern as llama ones — a copy with
a different section header, model, language and port:

```bash
cp ./configs/whisper.ini ./configs/whisper-en.ini   # edit model/language/port
whisper-server whisper-en --port 8082
```

### Running

```bash
# CLI — enters the container and starts whisper-server
whisper-server whisper --port 8081

# Or directly
distrobox enter rocm-llama-whisper -- whisper-server \
  --host 0.0.0.0 --port 8081 \
  -m ~/models/whisper/ggml-small.bin \
  --language de -t 4
```

> **Note:** m4a files work directly — no conversion needed.

### Environment Variables

```bash
# Use custom preset directory
LLAMA_CONFIG_DIR=~/.config/model-configs whisper-server whisper

# Use a different container name
LLAMA_WHISPER_CONTAINER=my-whisper whisper-server whisper
```

### Systemd

Same pattern as llama.cpp — auto-start on boot:

```bash
systemctl --user start whisper-server@whisper
systemctl --user enable whisper-server@whisper
```

The instance name matches the INI basename (`whisper` → `whisper.ini`).

### Integration with LobeHub

Point LobeHub at `http://<your-server>:8081` for the STT endpoint. whisper.cpp
uses a custom `POST /inference` endpoint (not OpenAI-compatible):

```bash
curl -X POST http://<your-server>:8081/inference \
  -H "Content-Type: multipart/form-data" \
  -F file="@audio.m4a" \
  -F language="de"
```

For OpenAI-compatible clients, a proxy may be needed.

## Image Generation — ComfyUI + FLUX Dev

Local image generation via [ComfyUI](https://github.com/comfyanonymous/ComfyUI) with the [ComfyUI-GGUF](https://github.com/city96/ComfyUI-GGUF) custom node, running **FLUX.1 [dev] Q4_K_S GGUF** on ROCm GPU. Exposed through:

- An **OpenAI-compatible** `POST /v1/images/generations` endpoint (LobeHub, curl)
- An **MCP tool** `generate_image` via Streamable HTTP at `http://localhost:8082/mcp` (OpenCode, agent frameworks)

Both run in the same process on `:8082` — one `systemctl start` brings up everything.

> **License note:** FLUX.1 [dev] has a non-commercial license. This is acceptable for purely local, personal use.

### Container Image

Uses the official AMD PyTorch+ROCm base image:

```bash
# Container is auto-created on first run
./comfyui-server flux-dev
```

Base image: `docker.io/rocm/pytorch:rocm7.2.2_ubuntu24.04_py3.12_pytorch_release_2.10.0`

### Model Download

Download the FLUX dev model (~16 GB total):

```bash
./scripts/download-flux-models.sh
```

| Component | File | Size |
|-----------|------|------|
| UNet (diffusion) — GGUF (bridge/MCP) | `flux1-dev-Q4_K_S.gguf` | ~6.8 GB |
| UNet (diffusion) — fp8 checkpoint (LobeHub ComfyUI provider) | `flux1-dev-fp8.safetensors` | ~11 GB |
| T5 text encoder | `t5xxl_fp16.safetensors` | ~9.5 GB |
| CLIP-L encoder | `clip_l.safetensors` | ~250 MB |
| VAE | `ae.safetensors` | ~320 MB |

Models are cached in `~/models/comfyui/{unet,clip,vae}`. ComfyUI reads this central
store directly via `configs/comfyui/extra_model_paths.yaml` (synced into the container
and passed with `--extra-model-paths-config`), so any model dropped there is picked up
automatically — no per-file symlinks under `~/ComfyUI/models`. The `/path/to/models`
placeholder in that file is substituted with `$MODELS_DIR` at launch, like the llama presets.

### Presets

Workflow JSON presets in `configs/comfyui/workflows/`:

| Preset | Size | Default Steps | Time (GPU) | Quality |
|--------|------|--------------|------------|---------|
| `flux-dev` | 1024×1024 | 20 | ~2-3 min | Best |
| `flux-dev-fast` | 1024×1024 | 20 | ~2-3 min | Good (8 for fast preview) |
| `flux-dev-3-2` | 1344×896 | 20 | ~2-3 min | Best |
| `flux-dev-2-3` | 896×1344 | 20 | ~2-3 min | Best |

Override steps per-request: `"steps": 8` for a fast preview, `"steps": 30` for highest quality.

### Setup

```bash
# One-time: install ComfyUI + deps inside the container
./scripts/setup-comfyui-container.sh

# One-time: download models
./scripts/download-flux-models.sh

# Start the server (single instance serves all workflow presets)
systemctl --user enable --now comfyui-server@comfyui
```

### Usage

```bash
# Generate an image via the OpenAI-compatible API
curl http://localhost:8082/v1/images/generations \
  -H "Content-Type: application/json" \
  -d '{
    "model": "flux-dev",
    "prompt": "a red apple on a wooden table",
    "width": 1024,
    "height": 1024,
    "steps": 25,
    "response_format": "url"
  }'

# Stream progress while generating (add Accept: text/event-stream)
curl http://localhost:8082/v1/images/generations \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{"model": "flux-dev-fast", "prompt": "a red apple"}'
# Outputs:
# data: {"type": "progress", "step": 5, "total": 20}
# data: {"type": "progress", "step": 10, "total": 20}
# ...
# data: {"type": "result", "data": [...], "seed": 42, "created": 1234567890}

# Fetch a previously generated image
curl http://localhost:8082/v1/images/2026-05-31/20260531T142301-a3f7c2d1.png --output out.png
```

Generated images are saved to `~/images/generated/YYYY-MM-DD/<timestamp>-<uuid8>.png` and served
at `GET /v1/images/{date}/{filename}`. Day-folders older than 7 days are cleaned up automatically
on each generation call (`IMAGE_RETENTION_DAYS` env var to change).

### MCP tool (OpenCode / agent frameworks)

```json
{
  "mcpServers": {
    "comfyui": {
      "transport": "http",
      "url": "http://localhost:8082/mcp"
    }
  }
}
```

The `generate_image(prompt, model, width, height, steps, seed)` tool returns `{url, seed}` for the generated image. The `seed` can be re-used (with different width/height/steps/model/prompt) to reproduce the same motif.

For best quality, pass `steps=25` with `flux-dev`. For fast previews, use `flux-dev-fast` with `steps=12`. All workflows default to `steps=20`.

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `COMFYUI_CONTAINER` | `comfyui-rocm` | Distrobox container name |
| `COMFYUI_IMAGE` | `rocm/pytorch:rocm7.2.2_...` | Container base image |
| `WORKFLOW_DIR` | `~/.config/comfyui/workflows` | Directory of workflow JSON templates |
| `BRIDGE_BASE_URL` | `http://localhost:8082` | Public base URL for image URLs returned by the MCP tool |
| `IMAGE_DIR` | `~/images/generated` | Where generated images are stored |
| `IMAGE_RETENTION_DAYS` | `7` | Days to keep old images before cleanup |

```bash
# Use a different base image
COMFYUI_IMAGE=docker.io/rocm/pytorch:latest ./comfyui-server

# Use a different container name
COMFYUI_CONTAINER=my-comfyui ./comfyui-server
```

### Systemd

```bash
systemctl --user start comfyui-server@comfyui
systemctl --user enable comfyui-server@comfyui
```

The instance name is arbitrary — a single unit serves all workflow presets.

### Integration with LobeHub

LobeHub can use image generation through either of two paths:

1. **Native ComfyUI provider (recommended)** — LobeHub's *ComfyUI* provider talks the
   native ComfyUI API directly. Point it at the ComfyUI server, not the bridge:

   - `COMFYUI_BASE_URL=http://<your-server>:8188`
   - Requires the FLUX.1-dev **fp8 `.safetensors` checkpoint** (GGUF files are not
     loadable by LobeHub's resolver/`UNETLoader`) — install with
     `./scripts/download-flux-models.sh`.
   - LobeHub resolves models through `CheckpointLoaderSimple`; the
     `checkpoints: unet` mapping in `extra_model_paths.yaml` makes the fp8
     checkpoint visible to it.

2. **OpenAI-compatible provider** — the bridge exposes `POST /v1/images/generations`
   and `GET /v1/models` in OpenAI format. Point an OpenAI-compatible provider at
   `http://<your-server>:8082/v1` instead.

## Available Presets

### LLM

Every preset below lives in `configs/`; launch by basename (or as the
`@`-instance of `systemctl --user start llama-server@<name>`).

- **`fork-router.ini`** — *(currently active)* Qwen3.8-27B ROCmFP4 (strict
  MTP + prompt caching, ~28 tok/s decode) + bge-m3 embeddings, both from
  one q38rocm v1.5.2 fork process (default unit `llama-server@fork-router`,
  port 8080)
- **`qwen3.8-27b-fp4-mtp.ini`** — same fork engine, standalone single-model lane
- **`qwen3.8-27b-stock.ini`** — Qwen3.8-27B UD-Q4_K_XL on the stock binary
  (17 tok/s, draft MTP head; swap-back lane)
- **`router.ini`** — stock llama.cpp multi-model preset (on-demand loading +
  LRU eviction), the pre-fork reference
- **`qwen3.6-35b-a3b.ini`** — Qwen3.6-35B-A3B (38.5 GB MoE, fast; available,
  not active since the fp4 lane covers it)
- **`qwen3-coder-next.ini`** — Qwen3-Coder-Next (86 GB MoE, agentic coding)
- **`qwen3-coder-30b.ini`** — Qwen3-Coder-30B (34 GB, OpenCode-compatible)
- **`devstral-small-24b.ini`** — Devstral-Small-2-24B (28 GB)
- **`gpt-oss-120b.ini`** — GPT-OSS-120B (61 GB, F16)
- **`nomic-embed-v1.5.ini`** — 768-dim embedding model
- **`bge-m3.ini`** — 1024-dim multilingual embedder (also served by `fork-router`)

### STT
- **whisper** — whisper.cpp `small` model, German, port 8081

### Image Generation
- **flux-dev** — 1024×1024, 20 steps, best quality (~2-3 min)
- **flux-dev-fast** — 1024×1024, 20 steps default (use `steps=8` for fast preview)
- **flux-dev-3-2** — 1344×896 landscape, 20 steps
- **flux-dev-2-3** — 896×1344 portrait, 20 steps

## Qwen3.8-27B

Dense 27B, hybrid DeltaNet attention. Every preset below stays in
`configs/` (and `~/.config/llama-cpp/`); the **active** serving is whichever
systemd instance is enabled — swap with `systemctl --user disable
llama-server@<a>` + `enable llama-server@<b>`.

### Active: q38rocm ROCmFPX fork (v1.5.2)

`configs/fork-router.ini` runs the community-optimized
[q38rocm](https://github.com/julianmb/q38rocm) v1.5.2 engine — ROCmFP4 block
quants, TurboQuant KV, strict-Qwen MTP. Measured on a 128 GB Strix Halo:
**~28 tok/s decode**, 4/4 draft acceptance, prompt caching coexists with MTP
(spec-stateful checkpoint salvage: repeat-request TTFT 15.2 s → 0.4 s),
byte-identical across cold and cache-restored runs. As of v1.5.2 the same
preset also serves `POST /v1/embeddings` natively.

The default systemd instance `llama-server@fork-router` serves both
`qwen3.8-27b-fp4-mtp` and `bge-m3` on port 8080 — the unit's drop-in
(`systemd/llama-server@fork-router.service.d/override.conf`) pins
`LLAMA_SERVER_BIN` to the v1.5.2 engine and the port. Wired to this repo
as opencode's default provider.

```bash
# Engine + weights
./scripts/download-q38rocm-engine.sh   # v1.5.2 static engine
./scripts/download-qwen38-model.sh     # ROCmFP4_FAST weights (13.55 GiB)

systemctl --user enable --now llama-server@fork-router   # port 8080
curl http://localhost:8080/v1/models
```

Swapping the active serving:

```bash
systemctl --user disable --now llama-server@fork-router
systemctl --user enable --now llama-server@qwen3.6-35b-a3b   # stock MoE lane
# or qwen3.8-27b-stock (stock Q4) / qwen3.8-27b-fp4-mtp (fork, single-model)
```

Trade-offs, verified on this machine:

- Drop `c` to `131072` in `fork-router.ini` to roughly halve the KV
  footprint (~35 GB claimed at 262144 → ~24 GB loaded).
- Fork router mode is fine for models that load fast; it cannot host
  multi-GB models as on-demand (the hardcoded child timeout and router
  exit on port-bind failure were investigated, root-caused, and reported
  upstream — both cases were environmental on this host), so keep big
  models eager-loaded.
- Router-mode `/v1/embeddings` works on the fork (verified 200, cosine
  ≈0.9998 vs stock bge-m3).

### Swap-back lane: stock llama.cpp

`configs/qwen3.8-27b-stock.ini` + `configs/router.ini` run unsloth's
**UD-Q4_K_XL** (17.6 GB) on the stock binary:
~17 tok/s decode, prompt caching works (repeat-request TTFT 13 s → 0.4 s),
byte-identical, and (unlike the fork) multi-model on-demand loading with LRU
eviction. `draft-mtp` measures neutral on the ROCm backend (16.9 vs
17.2 tok/s) — drop it to save the 3.2 GB draft.

```bash
# Weights (~21 GiB total)
curl -L -o ~/models/qwen3.8-27b/stock/Qwen3.8-27B-UD-Q4_K_XL.gguf \
  https://huggingface.co/unsloth/Qwen3.8-27B-GGUF/resolve/main/Qwen3.8-27B-UD-Q4_K_XL.gguf
curl -L -o ~/models/qwen3.8-27b/stock/mtp-Qwen3.8-27B-Q8_0.gguf \
  https://huggingface.co/ggml-org/Qwen3.8-27B-GGUF/resolve/main/mtp-Qwen3.8-27B-Q8_0.gguf
```

The qwen3.6-35b-a3b MoE lane is no longer active (fp4 covers it at half the
RAM), but `configs/qwen3.6-35b-a3b.ini` stays available as a swap-in.

## Embeddings

Set `embeddings = true` and (optionally) `pooling = mean|last|cls` in
the section. The `/v1/embeddings` endpoint serves any model with that
flag; the `/v1/chat/completions` endpoint serves any model that has a
chat template. With multiple sections in one preset the request's
`model` field selects which one runs.

## Frequently Used INI Keys

| INI key | Example | Notes |
|---------|---------|-------|
| `model` | `/path/to/model.gguf` | Required for non-cached models |
| `c` (`ctx-size`) | `262144` | Token context window |
| `b` (`batch-size`) | `2048` | Prompt batch size |
| `ub` (`ubatch-size`) | `2048` | Micro-batch size |
| `t` (`threads`) | `8` | CPU threads |
| `ngl` (`n-gpu-layers`) | `999` | Layers offloaded to GPU |
| `flash-attn` | `on` / `off` / `auto` | Flash attention |
| `jinja` / `no-jinja` | `true` | Required for tool calling |
| `no-mmap` | `true` | Recommended for Strix Halo |
| `cache-type-k` / `cache-type-v` | `q8_0` | KV cache quantization |
| `cache-reuse` | `4096` | Prompt cache reuse size |
| `kv-unified` | `true` | Unified KV cache |
| `embeddings` | `true` | Enable `/v1/embeddings` |
| `pooling` | `mean` / `last` / `cls` | Embedding pooling type |
| `spec-type` | `ngram-mod` | Speculative decoding type |
| `spec-ngram-size-n` | `10` | N-gram size |
| `draft-min` / `draft-max` | `12` / `24` | Speculative draft bounds |
| `chat-template-file` | `/abs/path.jinja` | Custom chat template |
| `load-on-startup` | `true` | Eager-load on server start (preset-only) |
| `stop-timeout` | `10` | Graceful-unload wait seconds (preset-only) |

Any other `llama-server --help` flag works too — drop the leading
dashes and use the long or short form.

## Systemd Service

A parameterized user service auto-starts a preset on boot:

```bash
# Start a preset (single-model or router)
systemctl --user start llama-server@fork-router

# Enable on boot
systemctl --user enable llama-server@fork-router

# Switch default
systemctl --user disable llama-server@fork-router
systemctl --user enable llama-server@qwen3-coder-next

# Status
systemctl --user status llama-server@fork-router
```

The instance name after `@` matches the preset basename (without `.ini`).

Engine overrides (e.g. the q38rocm fork) are per-instance drop-ins under
`~/.config/systemd/user/llama-server@<name>.service.d/`, setting
`LLAMA_SERVER_BIN` (fork binary) and `LLAMA_SERVER_PORT`. A non-default
`LLAMA_SERVER_BIN` makes the in-container launcher enable the fork env
block (HSA_OVERRIDE=11.5.1, unified memory, RADV). The shipped fork default
is in `systemd/llama-server@fork-router.service.d/override.conf`.

## Additional Arguments

Pass extra arguments directly to llama-server:

```bash
rocm-llama qwen3-coder-30b --port 8000 --n-predict 500 --threads-batch 16
```

The following are automatically set:
- `--host 0.0.0.0` (exposes on network by default)

## Troubleshooting

### Container not found

The first run will automatically create the container with the correct image. Subsequent runs will use the existing container.

### `chpasswd: invalid password hash` during container creation

Your distrobox is too old for the toolbox image (Fedora 44 base needs distrobox ≥ 1.8.2). See the version note under [Prerequisites](#ubuntu--distrobox).

### Model file not found

Ensure the `model = ...` path in your `.ini` exists and is accessible to the container. Paths should be absolute.

### Preset directory issues

```bash
# Show current preset directory in use
rocm-llama

# Use custom directory
LLAMA_CONFIG_DIR=/path/to/configs rocm-llama my-model --port 8000
```

### Tool calls not working

Ensure `jinja = true` is set in the section. This enables the jinja template engine required for tool/function calling in OpenCode and other tools.

### Cached HF models showing in `/v1/models`

llama.cpp reports any model under `~/.cache/llama.cpp` in `/v1/models`. The launcher passes `--no-models-autoload`, so they stay `unloaded` until something explicitly requests them with `?autoload=true` — they don't take resources by default.

## References

- [llama.cpp](https://github.com/ggml-org/llama.cpp) - The amazing inference engine
- [whisper.cpp](https://github.com/ggml-org/whisper.cpp) - Speech-to-text
- [ComfyUI](https://github.com/comfyanonymous/ComfyUI) - Node-based image generation
- [ComfyUI-GGUF](https://github.com/city96/ComfyUI-GGUF) - GGUF quantization for ComfyUI
- [kyuz0/amd-strix-halo-toolboxes](https://github.com/kyuz0/amd-strix-halo-toolboxes) - Containerized GPU toolchains
- [julianmb/q38rocm](https://github.com/julianmb/q38rocm) - ROCmFP4 engine fork for Qwen3.8-27B on Strix Halo
- [AMD PyTorch+ROCm Docker](https://hub.docker.com/r/rocm/pytorch) - Official GPU-accelerated PyTorch images
- [distrobox](https://distrobox.it/) - Container wrapper for easy integration
- [OpenCode](https://opencode.ai/) - AI-powered coding assistant

## License

This project is a configuration and tooling layer. Use in accordance with the licenses of the underlying projects (llama.cpp, amd-strix-halo-toolboxes, etc.).
