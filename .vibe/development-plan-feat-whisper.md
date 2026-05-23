# Feature: STT via whisper.cpp

## Goal

Add speech-to-text (STT) capability to the local-llm stack by integrating whisper.cpp as a companion service alongside the existing llama.cpp router.

## Engine Choice: whisper.cpp

- Same upstream (ggml-org) as llama.cpp — same build system, same ROCm backend
- Proven ROCm support on Strix Halo gfx1151 (Radeon 8060S) [discussion #3460]
- Ships `whisper-server` with an OpenAI-compatible `/v1/audio/transcriptions` endpoint
- Models are small (1.5–3 GB), so always-loaded-at-startup is acceptable
- Not part of llama.cpp itself (that only handles LLMs/embeddings/reranking)

## Build Strategy

Custom container image via `container/Containerfile.rocm-whisper`. This extends
kyuz0's `rocm-7.2` runtime image (which has all llama.cpp binaries) with a
multi-stage build:

1. **Builder stage** (`registry.fedoraproject.org/fedora:43`):
   - Installs ROCm 7.2 devel packages from AMD's repo (same as kyuz0's build)
   - Clones and builds whisper.cpp with `-DGGML_HIP=ON -DAMDGPU_TARGETS=gfx1151`
2. **Runtime stage** (`kyuz0/amd-strix-halo-toolboxes:rocm-7.2`):
   - Copies only `whisper-server` from the builder stage
   - No extra packages, no bloat — the resulting image has both llama.cpp and whisper.cpp

Build once, then create a distrobox from the local image.

## Model Selection

| Model | Size | VRAM | Quality |
|-------|------|------|---------|
| `base.en` | 147 MB | ~500 MB | Basic English |
| `small.en` | 466 MB | ~1 GB | Good English |
| `medium.en` | 1.5 GB | ~3 GB | Better English |
| `large-v3-turbo` | 1.5 GB | ~3 GB | Best quality, fast |
| `large-v3` | 3.1 GB | ~6 GB | Best quality, slower |

**Decision**: Start with `large-v3-turbo` for quality/speed balance. Model is downloaded once and cached. Language-specific models can be added per config.

## Architecture

```
┌──────────────┐    ┌──────────────────┐    ┌──────────────────┐
│  LobeHub     │    │  llama.cpp       │    │  whisper.cpp     │
│  flinker:8080├────┤  :8080            │    │  :8081            │
│  (WebUI)     │    │  (llm/embed)     │    │  (stt)           │
└──────────────┘    └──────────────────┘    └──────────────────┘
```

- Whisper server runs on a **separate port** (e.g., 8081) — independent binary, not a router model
- LobeHub points to both endpoints independently
- Uses a **separate distrobox container** (`rocm-llama-whisper`) built from `Containerfile.rocm-whisper`
- Shares the same GPU via ROCm

## Files to Create

### `whisper-server` (launcher, mirrors `llama-server`)
- CLI entry point: `whisper-server whisper [--port 8081]`
- No backend selection — uses the `rocm-llama-whisper` distrobox
- Enters the container and runs the baked-in wrapper at `/usr/local/bin/whisper-server-container`

### `whisper-server-container` (container-side wrapper, baked into image)
- Parses INI config from `$CONFIG_DIR/$PRESET_NAME.ini`
- Builds and execs `whisper-server` CLI with parsed values
- Baked into the image at `/usr/local/bin/` during `podman build`

### `configs/whisper.ini`
```ini
version = 1

[stt-default]
model = /home/jaegle/models/whisper/ggml-large-v3-turbo.bin
language = de
threads = 4
```

### `systemd/whisper-server@.service`
- Mirrors `llama-server@.service` pattern
- Instance arg is the config name
- `ExecStop` uses `pkill -f "whisper-server.*-m "` (matches by model path flag)

## Differences from llama.cpp Server

| Aspect | llama.cpp router | whisper.cpp server |
|--------|-----------------|-------------------|
| Binary | `llama-server` | `whisper-server` |
| Engine | Single binary, multi-model via `--models-preset` | Single binary, single model |
| Autoload | `--no-models-autoload` + `load-on-startup` | Not supported — model loaded at start |
| Model size | 10–60 GB | 0.15–3 GB |
| API path | `/v1/chat/completions` | `/v1/audio/transcriptions` |
| Metrics | `--metrics` | Not supported (single-model, always-on) |

## Container Image Approach

**Decision**: Custom image via `container/Containerfile.rocm-whisper` rather than
building inside the existing container. Reasoning:

| Aspect | In-place build | Custom image |
|--------|---------------|--------------|
| Reproducibility | Manual steps, state drifts | Single `podman build`, fully declarative |
| Image size | Bloats runtime container | Multi-stage, minimal layer added |
| Cleanup | Packages left installed | Build artifacts discarded |
| Documentation | Steps to document | One `Containerfile` is the doc |

The Containerfile extends `kyuz0/amd-strix-halo-toolboxes:rocm-7.2` with a
multi-stage build that compiles whisper.cpp in a separate Fedora 43 builder
stage and copies only `whisper-server` into the runtime image. The resulting
image (`rocm-llama-whisper`) contains both llama.cpp and whisper.cpp binaries.

## Files Created (implementation plan)

| File | Purpose |
|------|---------|
| `container/Containerfile.rocm-whisper` | Reproducible image build |
| `scripts/build-whisper-image.sh` | Convenience: build + create distrobox |
| `scripts/download-whisper-model.sh` | Download whisper models |
| `whisper-server` | Host-side launcher (enters container, runs server) |
| `whisper-server-container` | Container-side wrapper (parses INI, execs `whisper-server`) |
| `configs/whisper.ini` | Default STT preset |
| `systemd/whisper-server@.service` | Systemd user service |

## Implementation Notes

- whisper.cpp cmake flags: `-DGGML_HIP=ON -DAMDGPU_TARGETS=gfx1151 -DCMAKE_BUILD_TYPE=Release`
- whisper-server does NOT support `--metrics` or `--models-preset` — it's a single-model server
- Stop signal uses `pkill -f "whisper-server.*-m "` (matches by model path flag)
- Model: `large-v3-turbo` recommended (~1.5 GB, best quality/speed ratio)
- The `whisper-server` wrapper follows the same pattern as `llama-server` but simplified

## Future Considerations

- Add TTS via llama.cpp's built-in `--model-vocoder` to the router config
- Add vision model (e.g., Gemma 3 Vision) to the router config
