# Local LLM Server - Easy Model Experiments with llama.cpp

This repository makes it easy to launch and experiment with different LLM models in [llama.cpp](https://github.com/ggml-org/llama.cpp) across different GPU backends (ROCm, Vulkan), with support for saving experiment configurations for reproducibility.

## Overview

The goal is to provide a simple, reproducible way to:
- Launch llama.cpp models with pre-configured settings
- Experiment with different models, context sizes, batch sizes, and optimization flags
- Save working configurations for future reference
- Support multiple GPU backends via containerized environments

## Prerequisites

### Ubuntu + Distrobox

This setup uses [distrobox](https://distrobox.it/) to run containerized GPU toolchains. This is necessary on Ubuntu because the containerized environments from [kyuz0/amd-strix-halo-toolboxes](https://github.com/kyuz0/amd-strix-halo-toolboxes) don't work natively with Ubuntu's default container setup. See [this issue](https://github.com/kyuz0/amd-strix-halo-toolboxes/issues/16) for details.

**Install distrobox:**
```bash
curl -s https://raw.githubusercontent.com/89luca89/distrobox/main/install | sudo sh
```

### Container Images

This project uses the amazing [kyuz0/amd-strix-halo-toolboxes](https://github.com/kyuz0/amd-strix-halo-toolboxes) which provides pre-built containerized environments for different GPU backends:

- **ROCm 7.2**: `docker.io/kyuz0/amd-strix-halo-toolboxes:rocm-7.2`
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

Each preset is an `.ini` file in `./configs/` consumed directly by
`llama-server --models-preset` (router mode). A preset can hold one or
several models — the section header is the alias used in the OpenAI
`model` field.

Single-model preset (`./configs/qwen3-coder-30b.ini`):

```ini
version = 1

[qwen3-coder-30b]
model = /path/to/model.gguf
c = 262144
b = 2048
ub = 2048
t = 8
ngl = 999
flash-attn = on
jinja = true
load-on-startup = true
```

Multi-model preset (`./configs/router.ini`) keeps each section
separately and llama-server routes by request `model` field:

```ini
version = 1

[*]                  ; defaults shared by every section in this file
ngl = 999
b = 2048
ub = 2048

[qwen3.6-35b-a3b]
model = /path/to/qwen.gguf
c = 262144
flash-attn = on
jinja = true
load-on-startup = true

[nomic-embed-v1.5]
model = /path/to/nomic.gguf
c = 2048
embeddings = true
pooling = mean
load-on-startup = true
```

INI keys are llama-server CLI flag names without the leading dashes
(`--n-gpu-layers` → `n-gpu-layers` or its short alias `ngl`). For
boolean flags use `true`/`false`; flags that take a value (e.g.
`flash-attn`) take that value as-is. Settings under `[*]` apply to
every section in the file (and to any cached HF models). Two
preset-only keys: `load-on-startup = true` (eager-load on server start)
and `stop-timeout = N` (seconds to wait for graceful unload).

The launcher always passes `--no-models-autoload`, so cached HF models
listed in `/v1/models` won't auto-load on first request — only the
sections you defined with `load-on-startup = true` come up.

### Environment Variables

```bash
# Use custom preset directory
LLAMA_CONFIG_DIR=~/.config/model-configs rocm-llama qwen3-coder-30b --port 8000

# Or set permanently
export LLAMA_CONFIG_DIR=~/.config/model-configs
```

## Script Architecture

### Host-side (Entry Points)

- **`rocm-llama`** — wrapper → `llama-server rocm`
- **`vulkan-llama`** — wrapper → `llama-server vulkan`
- **`llama-server`** — orchestrator that creates the distrobox container
  on first use, copies presets and the wrapper into it, then enters the
  container

### Container-side

- **`llama-server-container`** — exec's
  `llama-server --models-preset <preset>.ini --no-models-autoload`. No
  flag-translation logic — llama.cpp parses the INI directly.

## Adding a New Model

Drop a new `.ini` in `./configs/` and launch it by basename:

```bash
cat > ./configs/my-model.ini <<'EOF'
version = 1

[my-model]
model = /path/to/model.gguf
c = 4096
ngl = 999
flash-attn = on
jinja = true
load-on-startup = true
EOF

rocm-llama my-model --port 8000
```

If the distrobox container already exists, copy the file into the
container's view (host `$HOME` is shared, so this is just a `cp`):

```bash
cp ./configs/my-model.ini ~/.config/llama-cpp/
```

## Available Presets

- **router** — qwen3.6-35b-a3b + nomic-embed-v1.5 from one process
  (default systemd unit)
- **qwen3.6-35b-a3b** — Qwen3.6-35B-A3B (38.5 GB, MoE 3B active; chat + embeddings)
- **qwen3-coder-next** — Qwen3-Coder-Next (86 GB MoE, agentic coding)
- **qwen3-coder-30b** — Qwen3-Coder-30B (34 GB, OpenCode-compatible)
- **devstral-small-24b** — Devstral-Small-2-24B (28 GB)
- **gpt-oss-120b** — GPT-OSS-120B (61 GB, F16)
- **nomic-embed-v1.5** — 768-dim embedding model

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
systemctl --user start llama-server@router

# Enable on boot
systemctl --user enable llama-server@router

# Switch default
systemctl --user disable llama-server@router
systemctl --user enable llama-server@qwen3-coder-next

# Status
systemctl --user status llama-server@router
```

The instance name after `@` matches the preset basename (without `.ini`).

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
- [kyuz0/amd-strix-halo-toolboxes](https://github.com/kyuz0/amd-strix-halo-toolboxes) - Containerized GPU toolchains
- [distrobox](https://distrobox.it/) - Container wrapper for easy integration
- [OpenCode](https://opencode.ai/) - AI-powered coding assistant

## License

This project is a configuration and tooling layer. Use in accordance with the licenses of the underlying projects (llama.cpp, amd-strix-halo-toolboxes, etc.).
