# ADR 0004: MCP Image Tool + On-Generation Cleanup

## Status

**Accepted**

## Context

ADR 0003 established local image generation via ComfyUI + FLUX Dev, exposed as an OpenAI-compatible
`POST /v1/images/generations` endpoint on `:8082` (used by LobeHub). This ADR extends that setup to:

1. Make image generation available as an **MCP tool** for agent frameworks (OpenCode etc.)
2. Fix the **`WORKFLOW_FILE` singleton bug** where the `model` field in API requests was silently ignored
3. Add **persistent image storage** with a `GET /v1/images/{date}/{filename}` endpoint
4. Define a **cleanup strategy** for generated images
5. Make the ComfyUI polling **async-safe** so the event loop is not blocked during 1–3 min generation

### Problems with the previous design

| Problem | Detail |
|---------|--------|
| `WORKFLOW_FILE` singleton | `WORKFLOW_FILE` was set once at process start; all requests used the same workflow regardless of the `model` field |
| No MCP exposure | Agent frameworks using MCP (OpenCode) had no way to trigger image generation without calling the REST API directly |
| No image persistence | Images were only accessible via ComfyUI's internal `127.0.0.1:8188/view` URL — unreachable from pods/containers |
| Sync polling blocks event loop | `wait_for_prompt()` polled with `time.sleep()` in the request handler — blocked all other requests during generation |
| Base64 in agent context | Returning `b64_json` to MCP would flood the agent context window with ~1 MB of base64 |

## Decision

### 1. MCP baked into `bridge.py` — single process, single port

Mount a FastMCP app onto the existing FastAPI instance:

```python
app = FastAPI(title="ComfyUI OpenAI Bridge")
mcp = FastMCP("comfyui-image-tool")
app.mount("/mcp", mcp.streamable_http_app())
```

**Why not a separate process**: one systemd unit, one port, no extra launcher changes. The
FastMCP SDK supports mounting as an ASGI sub-app on an existing FastAPI app natively.

### 2. MCP transport: Streamable HTTP

- Transport: `POST http://localhost:8082/mcp`
- No persistent connection — each tool call is a self-contained POST
- Compatible with OpenCode's `{ "transport": "http", "url": "..." }` config

SSE and stdio were rejected: SSE requires a persistent connection that complicates distrobox
lifetime management; stdio requires a separate process.

### 3. WORKFLOW_FILE → WORKFLOW_DIR

Replace the singleton env var with a directory:

```
WORKFLOW_DIR=/path/to/workflows
```

At request time: `WORKFLOW_DIR / <model>.json` — one file per model, resolved per-request.
The `model` field in `POST /v1/images/generations` and the `generate_image` MCP tool
both use this same resolution path.

### 4. Timestamp + UUID filenames, date-based folders

```
~/images/generated/
  YYYY-MM-DD/
    <YYYYMMDDTHHmmSS>-<uuid8>.png
```

Example: `~/images/generated/2026-05-31/20260531T142301-a3f7c2d1.png`

- **Sortable**: timestamp prefix sorts by generation time without a database
- **Unique**: uuid8 (8 hex chars of uuid4) is sufficient within a single second
- **Filesystem-safe**: no spaces, no special chars
- **Routable**: `GET /v1/images/{date}/{filename}` — no glob, direct `Path` lookup

Served at `http://localhost:8082/v1/images/{date}/{filename}` with `Content-Type: image/png`.

### 5. On-generation cleanup — no systemd timer

At the start of each `generate_images()` / `generate_image()` call:

```python
cleanup_old_images(IMAGE_DIR, IMAGE_RETENTION_DAYS)
```

Scans `IMAGE_DIR` for ISO-date-named subdirectories older than the retention window and
`shutil.rmtree()`s each one. Non-date-named entries are silently skipped.

**Why not a systemd timer**: fewer moving parts — no extra `.timer` and `.service` units to
install, copy, and maintain. The "stale if idle" trade-off is irrelevant for a personal local
stack where the service is either running (and generating) or off entirely.
`IMAGE_RETENTION_DAYS` defaults to 7 and is overridable via env var.

### 6. Async-safe polling via `asyncio.to_thread`

```python
async def wait_for_prompt_async(prompt_id, timeout=1200):
    return await asyncio.to_thread(_sync_poll, prompt_id, timeout)
```

The sync poll loop (using `requests` + `time.sleep`) runs in a thread pool thread so
the event loop remains free during the 1–3 min generation window. FastMCP SSE heartbeats
and other concurrent HTTP requests are not stalled.

### 7. MCP tool returns structured JSON, not base64

The `generate_image` MCP tool returns a structured `ImageGenerationResult` with `.url` and `.seed`:

```json
{
  "url": "http://localhost:8082/v1/images/2026-05-31/20260531T142301-a3f7c2d1.png",
  "seed": 1744492399
}
```

This keeps the agent context clean (~80 chars vs ~1.4 MB of base64). The `seed` field lets agents
re-use a seed from a previous result to reproduce the same image motif. The `POST /v1/images/generations`
endpoint retains `b64_json` as the default for backward compatibility with LobeHub.

### 8. Refactored into 5 files

The monolithic `bridge.py` was split to avoid circular imports and separate concerns:

| File | Responsibility |
|------|--------------|
| `bridge.py` | Utilities: `make_image_filename`, `cleanup_old_images`, `save_image_to_disk`, `wait_for_prompt_async`, `load_workflow`, `inject_prompt`, `get_image_data`, `ImageGenerationRequest` |
| `routes.py` | FastAPI REST routes: `POST /v1/images/generations`, `GET /v1/images/{date}/{filename}`, `GET /v1/models`, `GET /health` |
| `mcp_tools.py` | MCP tool: `generate_image` + `ImageGenerationResult` + `ModelChoice` |
| `main.py` | Entry point: creates `FastAPI(app)`, wires MCP lifespan, includes routes |
| `comfyui-bridge.py` | Stub for systemd `pkill` compatibility (imports `main.py`) |

## Consequences

### Positive

- Agent frameworks (OpenCode) can generate images natively via MCP — no REST API wiring required
- All workflow presets served from a single bridge process — one systemd unit for everything
- `model` field in API requests now correctly selects the workflow (bug fixed)
- Generated images are persistent and reachable via stable URLs
- Event loop not blocked during generation — concurrent requests handled normally
- No new systemd units to install for cleanup

### Negative

- `WORKFLOW_FILE` env var is removed; any external scripts using it must migrate to `WORKFLOW_DIR`
- Systemd unit instance name is no longer the preset name — callers using `comfyui-server@flux-dev`
  must update to `comfyui-server@comfyui` (or any name)
- `mcp[cli]` added as a runtime dependency (~several MB)
- Image cleanup only runs during generation — a long idle period leaves stale images until next run

### Neutral

- `b64_json` default preserved for LobeHub — no LobeHub config changes required
- `GET /v1/images/{date}/{filename}` is a new public endpoint but contains no auth; acceptable
  for a local-only service

## Implementation

- `comfyui-bridge/bridge.py` — utilities, config, models
- `comfyui-bridge/routes.py` — FastAPI REST routes
- `comfyui-bridge/mcp_tools.py` — MCP tool `generate_image`
- `comfyui-bridge/main.py` — entry point, app creation, MCP lifespan wiring
- `comfyui-bridge/comfyui-bridge.py` — systemd pkill-compatible stub
- `comfyui-bridge/requirements.txt` — `mcp[cli]`, `httpx`
- `comfyui-bridge/requirements-dev.txt` — `pytest`, `pytest-asyncio`
- `comfyui-server-container` — updated to pass `WORKFLOW_DIR`, removed preset arg
- `comfyui-server` — updated to not require preset arg; syncs all workflows at once; passes `HOST_HOSTNAME`
- `systemd/README.md` — documented MCP endpoint, image storage, seed usage

## Related

- ADR 0003: Local Image Generation via ComfyUI + FLUX Dev GGUF
- FastMCP: `mcp.server.fastmcp.FastMCP` — `streamable_http_app()` mounts as ASGI sub-app
- OpenCode MCP config: `{ "transport": "http", "url": "http://localhost:8082/mcp" }`
