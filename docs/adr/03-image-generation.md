# ADR 0003: Local Image Generation via ComfyUI + FLUX Dev GGUF

## Status

**Accepted**

## Context

The local-llm stack currently provides:

- **LLM inference** via `llama.cpp` (chat, embeddings, tools)
- **Speech-to-text** via `whisper.cpp`

Both are exposed through OpenAI-compatible APIs so that agents like LobeHub can consume them without custom plugins. However, **image generation is missing**, forcing agents to fall back to external APIs (OpenAI DALL-E, etc.) or skip visual tasks entirely.

Adding local image generation enables fully offline, private agent workflows where LobeHub can generate images, diagrams, and thumbnails on demand without leaving the local network.

### Boundary Conditions

| Resource | Limit | Implication |
|----------|-------|-------------|
| **Total RAM** | 109 GB | LLM (35B, ~38 GB) + Whisper (~3 GB) + Image Gen (~16 GB) = ~57 GB comfortably. The 86B model (~86 GB) cannot coexist with image gen and must remain `load-on-startup = false`. |
| **GPU** | AMD Strix Halo (gfx1151), ROCm 7.2 | All image gen must run on ROCm via PyTorch. No CUDA. Unified memory allows fallback to system RAM. |
| **Storage** | 631 GB free | Models are large (~16 GB for FLUX schnell Q4 + T5 + VAE), but disk is not a constraint. |
| **Container runtime** | `distrobox` + `podman` | New service must follow the existing pattern: lazy container creation, host wrapper script, systemd template service. |
| **Usage pattern** | Image gen rarely used | Services should be on-demand spin-up/down capable, though initially we run always-on. Auto-suspend is a future enhancement. |
| **API compatibility** | LobeHub expects OpenAI format | ComfyUI's native node-graph API must be bridged to `POST /v1/images/generations`. |
| **Aspect ratios** | 3:2 and 2:3 required for common use cases | Workflow templates must support multiple aspect ratios. |

## Decision

We will add local image generation using **ComfyUI** with the **ComfyUI-GGUF** custom node, running **FLUX.1 [dev] Q4_K_S GGUF** as the diffusion model, exposed through a **custom Python FastAPI bridge** that translates OpenAI-compatible requests to ComfyUI workflow JSONs.

The service follows the existing stack patterns:
- **Host wrapper**: `comfyui-server` (lazy distrobox creation, config sync)
- **Container wrapper**: `comfyui-server-container` (ROCm env vars, starts ComfyUI + bridge)
- **Systemd template**: `systemd/comfyui-server@.service` (always-on, `Restart=on-failure`)

### Component Choices

**1. Model: FLUX.1 [dev] Q4_K_S GGUF**
- Non-commercial license (acceptable for this purely local, personal stack)
- Best absolute quality among open FLUX models: 20–50 sampling steps, superior detail and coherence
- Transformer/DiT architecture handles quantization gracefully
- ~6.8 GB UNet + ~5 GB T5 + ~3 GB VAE/CLIP = **~14–16 GB total**, fitting alongside 35B LLM
- Excellent text-in-image rendering
- Same RAM footprint as schnell but significantly higher quality

**2. Backend: ComfyUI + ComfyUI-GGUF**
- Only mature backend with native GGUF support for FLUX models
- ROCm support via PyTorch (matches our GPU stack)
- Flexible workflow JSON system makes aspect ratio switching trivial
- Well-maintained, active community

**3. OpenAI Bridge: Custom Python FastAPI**
- ~100 lines of Python with `fastapi` + `requests`
- Loads pre-built workflow JSON templates, injects prompt/size/seed
- Submits to ComfyUI `/prompt`, polls `/history`, returns OpenAI-format response
- No external Rust dependency (unlike `Comfyui2Openai` which is unmaintained and would require Rust toolchain)
- Full control over ComfyUI-GGUF-specific node mappings

**4. Bridge Location: Inside the distrobox**
- Single systemd unit lifecycle: `systemctl start` brings up both ComfyUI and bridge
- `systemctl stop` tears both down
- Port `8188` (ComfyUI internal) and `8082` (bridge external)

**5. Lifecycle: Always-on (initially)**
- `Restart=on-failure` in systemd unit
- Auto-suspend (idle timeout → auto-stop) is deferred to a future enhancement
- ~30 second cold start if manually stopped and restarted later

**6. Aspect Ratios & Speed Presets: Pre-built workflow templates**
- `flux-dev.json` → 1024×1024 (1:1), **20 steps** — best quality (~2–3 min)
- `flux-dev-fast.json` → 1024×1024 (1:1), **8 steps** — faster preview (~1 min), same model file
- `flux-dev-3-2.json` → 1344×896 (3:2 landscape), 20 steps
- `flux-dev-2-3.json` → 896×1344 (2:3 portrait), 20 steps
- OpenAI `size` parameter selects the appropriate template

## Consequences

### Positive

- Agents like LobeHub can generate images locally without external API calls
- Full privacy — no images or prompts leave the local network
- Fits within existing RAM budget when LLM router only loads the ~35B model
- Follows established stack patterns (distrobox, systemd templates, INI/JSON presets)
- Non-commercial license is acceptable for this purely local, personal stack
- Quantized GGUF models keep disk and RAM footprint reasonable
- Multiple aspect ratios support common use cases (thumbnails, portraits, landscapes)

### Negative

- **Cannot coexist with the 86B model**: If `qwen3-coder-next` (~86 GB) is loaded, image generation will OOM. The 86B model must stay on `load-on-startup = false`.
- **Slower than schnell**: Full-quality dev requires ~2–3 minutes per image on GPU (vs. ~15 seconds for schnell). Mitigated by `flux-dev-fast` preset (8 steps, ~1 minute) for quick previews.
- **Cold start latency**: If auto-suspend is added later, ~30 seconds to load models from NVMe on first request
- **No persistent image storage strategy**: Images are saved in ComfyUI's output folder; no cleanup policy defined yet
- **ComfyUI web UI exposed**: Port 8188 serves the ComfyUI interface while running; acceptable since this is a local-only service
- **Workflow template maintenance**: If ComfyUI-GGUF node types change, workflow JSONs may need updating

### Neutral

- ComfyUI is heavier than a minimal script, but necessary for GGUF support
- The bridge is custom code requiring maintenance, but the alternative (unmaintained Rust proxy) is worse
- Always-on consumes ~16 GB RAM continuously; auto-suspend can be layered on top later without architectural changes

## Options Considered

### Image Generation Models

| Model | Size (Q4) | Steps | License | Pros | Cons |
|-------|-----------|-------|---------|------|------|
| FLUX.1 [schnell] GGUF | ~14–16 GB total | 1–4 | Apache 2.0 | Fastest; good quality | Not quite FLUX dev quality |
| **FLUX.1 [dev] GGUF** | ~14–16 GB total | 20–50 | **Non-commercial** | **Absolute best quality**; excellent text; fits RAM | Slower (~2–3 min on GPU); license restricts commercial use |
| SD3.5 Large GGUF | ~10 GB total | 20–50 | Stability AI community | Smaller footprint | Text rendering weaker; community prefers FLUX |
| SD3.5 Large Turbo GGUF | ~10 GB total | 4–8 | Stability AI community | Faster SD3.5 variant | Outclassed by FLUX schnell |
| SDXL + Lightning | ~6–7 GB | 4 | Various | Very fast sketches | Lower quality; no GGUF; more complex |

### Inference Backends

| Option | Pros | Cons |
|--------|------|------|
| **ComfyUI + ComfyUI-GGUF** | Native GGUF; ROCm works; flexible workflows; well-maintained | Heavier than minimal script |
| Stable Diffusion WebUI (A1111) | Familiar UI | No native GGUF; heavier; API less flexible |
| Custom Python script (diffusers) | Minimal overhead | No GGUF support for FLUX in diffusers |

### OpenAI Bridges

| Option | Pros | Cons |
|--------|------|------|
| **Custom Python bridge** | Full control; no external deps; uses existing Python | Requires maintenance |
| `qup1010/Comfyui2Openai` (Rust) | Existing project | 4 stars, unmaintained; needs Rust; node mappings may mismatch |
| No bridge — direct ComfyUI API | Zero code | LobeHub cannot use without custom plugin |

### Bridge Locations

| Option | Pros | Cons |
|--------|------|------|
| **Inside distrobox** | Single unit lifecycle; shared localhost | Tied to ComfyUI lifecycle |
| Host-side bare Python | Independent restart | Reaches into container (port forwarding solves this) |

### Lifecycle Strategies

| Option | Pros | Cons |
|--------|------|------|
| **Always-on** | Immediate response; simple | Continuously consumes ~16 GB RAM |
| Manual start/stop | Perfect control | Easy to forget; agents must know to start first |
| Auto-suspend (future) | Frees RAM automatically | ~30s cold-start penalty; needs timeout logic |

## Related

- `city96/ComfyUI-GGUF` — GGUF quantization support for ComfyUI
- `city96/FLUX.1-dev-gguf` — Pre-quantized model files
- Existing stack patterns: `llama-server`, `whisper-server`, `systemd/*.service`

## Implementation Notes (2026-05-29)

### Models installed
Both FLUX.1 variants are installed as Q4_K_S GGUF files (verified via `GET /object_info/UnetLoaderGGUF`):
- `flux1-dev-Q4_K_S.gguf` — primary model (ADR target); 20–50 steps, best quality
- `flux1-schnell-Q4_K_S.gguf` — fast alternative; 1–4 steps, ~15 s/image; Apache 2.0

Quantization is transparent to consumers — LobeHub and the OpenAI bridge submit prompts and receive images; the `.gguf` filename is only referenced inside ComfyUI workflow JSON templates via the `UnetLoaderGGUF` node.

### LobeHub integration: OpenAI bridge workaround (current)

**Intended integration**: LobeHub has a built-in ComfyUI provider that speaks ComfyUI's native WebSocket + REST API directly via `COMFYUI_BASE_URL=http://flinker:8188`. This is the long-term target.

**Current workaround**: The native ComfyUI provider is blocked by an upstream bug in `packages/model-runtime`: `LobeComfyUI.createImage()` calls `${APP_URL}/webapi/create-image/comfyui` using `process.env.APP_URL`, which is the public HTTPS domain (`https://lobehub.no-panic.org`). The request goes through Traefik → oauth2-proxy and is blocked with an HTML redirect before Next.js can validate the internal bearer token. `INTERNAL_APP_URL` is not read by `LobeComfyUI` — it only reads `APP_URL`. Setting `APP_URL=localhost` fixes the loopback but breaks Better Auth OAuth callbacks (which require the public domain as `baseURL` for GitHub redirect URIs).

**Workaround**: Use the OpenAI bridge (`:8082`) via LobeHub's **Xinference provider slot** instead. `xinference` uses `createOpenAICompatibleRuntime` which calls `POST /v1/images/generations` directly on the configured `baseURL` — no `APP_URL` loopback involved. The async task worker calls `http://flinker:8082/v1` directly from within the pod.

Wired via `homelab-apps` Pulumi stack:
- `lobehub:enableImageGen = true` — opt-in flag
- `lobehub:flinkerImageUrl = http://flinker:8082/v1` — xinference proxy URL
- Injects: `XINFERENCE_API_KEY=not-needed`, `XINFERENCE_PROXY_URL`, `XINFERENCE_MODEL_LIST=flux-dev`

**Bridge fix required**: The bridge's default `response_format` changed from `"url"` to `"b64_json"` to avoid returning `http://127.0.0.1:8188/view?...` URLs that are only reachable locally on flinker. The bridge always fetches image bytes internally anyway, so base64 inline is strictly better for remote callers.

**Migration path**: When upstream LobeHub adds `INTERNAL_APP_URL` support to `LobeComfyUI.createImage()` (reading `process.env.INTERNAL_APP_URL || process.env.APP_URL`), switch back to:
- `lobehub:enableComfyUI = true` + `lobehub:comfyuiUrl = http://flinker:8188`
- Remove `enableImageGen` / `flinkerImageUrl` config
- The native ComfyUI provider gives richer workflow control (steps, CFG, seeds, etc.)

The FastAPI OpenAI bridge (`:8082`) remains in place for other consumers (CLI tools, other agents) regardless of which LobeHub integration is active.
