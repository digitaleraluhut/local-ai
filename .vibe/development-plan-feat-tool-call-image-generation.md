# Development Plan: local-ai (feat/tool-call-image-generation branch)

*Generated on 2026-05-31 by Vibe Feature MCP*
*Workflow: [epcc](https://codemcp.github.io/workflows/workflows/epcc)*

## Goal

Allow agent frameworks (OpenCode, LobeHub) to trigger local image generation via an
MCP `generate_image` tool baked directly into the existing ComfyUI bridge
(`comfyui-bridge/bridge.py`). The bridge is simultaneously:

1. An OpenAI-compatible REST API on `:8082` (existing, used by LobeHub)
2. An MCP server at `http://localhost:8082/mcp` using Streamable HTTP transport (new)

Generated images are saved to disk and served via a new `GET /v1/images/{id}` endpoint.
The MCP tool returns a short URL — no base64 ever enters the agent context.

## Key Decisions (all finalized)

### 1. MCP baked into bridge.py (not a separate file)

The Python MCP SDK (`mcp[cli]`) supports **mounting a FastMCP server onto an existing
FastAPI app** via `app.mount("/mcp", mcp.streamable_http_app())`. This means one
process, one port (`:8082`), one systemd unit lifecycle. No new launcher changes needed.

```python
# bridge.py — single FastAPI process serving both:
app = FastAPI(title="ComfyUI OpenAI Bridge")
mcp = FastMCP("ComfyUI Image Generation")

@mcp.tool()
async def generate_image(prompt: str, model: str = "flux-dev-fast", size: str = "1024x1024") -> str:
    ...  # calls internal generation logic, saves PNG, returns URL

app.mount("/mcp", mcp.streamable_http_app())
```

### 2. MCP transport: Streamable HTTP (not SSE, not stdio)

- Transport: `POST http://localhost:8082/mcp` (Streamable HTTP, MCP spec 2025-06-18)
- FastMCP SDK mounts it as an ASGI sub-app on the existing FastAPI instance
- No persistent connection needed — each tool call is a POST, response is JSON or SSE-streamed per-request
- OpenCode config: `{ "transport": "http", "url": "http://localhost:8082/mcp" }`

### 3. Image handling: date-based folders + timestamp-UUID filenames (no base64 in context)

- Generated images saved to `~/images/generated/YYYY-MM-DD/<timestamp>-<uuid>.png`
  - Example: `~/images/generated/2026-05-31/20260531T142301-a3f7c2d1.png`
  - Timestamp: `%Y%m%dT%H%M%S` (compact ISO 8601, sortable, filesystem-safe)
  - UUID: 8 hex chars (first segment of uuid4 — sufficient uniqueness within a day)
- New `GET /v1/images/{date}/{filename}` endpoint serves the PNG directly (`Content-Type: image/png`)
- MCP tool returns: `"Image generated: http://localhost:8082/v1/images/YYYY-MM-DD/<timestamp>-<uuid>"`
- Short URL in context → no contamination, renderable by any HTTP client
- Filenames are sortable by generation time without a database

### 4. Disk cleanup: on-generation cleanup with date-based folders (no systemd timer)

- **Approach**: at the start of each `generate_image` call, scan `~/images/generated/` for
  day-folders older than the grace period and `shutil.rmtree()` each one atomically
- **Why not systemd timer**: fewer moving parts, no extra files to install/maintain;
  the "stale if idle" tradeoff is irrelevant for a personal local stack
- **Grace period**: 7 days (`IMAGE_RETENTION_DAYS` env var, default 7)
- **Cost**: one `os.listdir()` + N cheap `rmtree()` calls — negligible vs. 1–3 min inference

```python
def cleanup_old_images(base_dir: Path, grace_days: int = 7) -> None:
    cutoff = date.today() - timedelta(days=grace_days)
    for day_dir in base_dir.iterdir():
        try:
            if date.fromisoformat(day_dir.name) < cutoff:
                shutil.rmtree(day_dir)
        except ValueError:
            pass  # ignore non-date-named entries
```

### 5. Bridge fix: dynamic workflow selection (WORKFLOW_FILE → WORKFLOW_DIR)

- **Current bug**: `WORKFLOW_FILE` is a process-level env var singleton; the `model`
  field in `POST /v1/images/generations` requests is completely ignored
- **Fix**: `WORKFLOW_DIR` env var points to the workflows directory; at request time,
  `model` name maps to `<WORKFLOW_DIR>/<model>.json`
- `comfyui-server-container` updated: pass `WORKFLOW_DIR` instead of `WORKFLOW_FILE`
- One bridge process now serves all models (no longer started per-preset)

### 6. Async-safe ComfyUI polling

- Current bridge uses sync `requests` + polling loop — blocks the event loop
- Fix: wrap ComfyUI polling in `asyncio.to_thread()` so FastAPI + MCP SSE heartbeats
  are not stalled during 1–3 min image generation

### 7. Tool schema for generate_image

```json
{
  "name": "generate_image",
  "description": "Generate an image from a text prompt using the local FLUX model. Returns a URL to the generated image.",
  "parameters": {
    "type": "object",
    "properties": {
      "prompt": {
        "type": "string",
        "description": "Detailed text description of the image to generate"
      },
      "model": {
        "type": "string",
        "enum": ["flux-dev", "flux-dev-fast", "flux-dev-3-2", "flux-dev-2-3"],
        "default": "flux-dev-fast",
        "description": "Workflow preset: flux-dev (best quality ~2-3 min), flux-dev-fast (~1 min), flux-dev-3-2 (landscape 3:2), flux-dev-2-3 (portrait 2:3)"
      },
      "size": {
        "type": "string",
        "default": "1024x1024",
        "description": "Image dimensions as WxH (e.g. 1024x1024). Overrides preset default."
      }
    },
    "required": ["prompt"]
  }
}
```

## Files to create / modify

| File | Action | Description |
|------|--------|-------------|
| `comfyui-bridge/bridge.py` | **Modify** | Fix WORKFLOW_DIR; date-based storage with `<timestamp>-<uuid8>.png` filenames + on-gen cleanup; `GET /v1/images/{date}/{filename}`; mount FastMCP at `/mcp`; async polling |
| `comfyui-bridge/requirements.txt` | **Create** | `fastapi`, `uvicorn`, `requests`, `httpx`, `mcp[cli]` |
| `comfyui-bridge/requirements-dev.txt` | **Create** | `pytest`, `pytest-asyncio`, `httpx` (test client) |
| `comfyui-bridge/test_bridge.py` | **Create** | TDD test suite (red→green per increment) |
| `comfyui-server-container` | **Modify** | Pass `WORKFLOW_DIR` instead of `WORKFLOW_FILE`; remove per-preset startup |
| `comfyui-server` | **Modify** | No longer pass preset as workflow file arg; sync bridge changes |
| `systemd/README.md` | **Modify** | Document MCP endpoint; remove placeholder for cleanup units |
| `README.md` | **Modify** | Document MCP endpoint, updated bridge, new `GET /v1/images/{date}/{filename}` endpoint |
| `docs/adr/04-mcp-image-tool.md` | **Create** | ADR documenting MCP + on-generation cleanup decisions |

## Architecture after this change

```
comfyui-bridge/bridge.py  (single process on :8082)
├── POST /v1/images/generations         # OpenAI-compat (LobeHub, curl)
│     └── picks <WORKFLOW_DIR>/<model>.json dynamically
│     └── cleans up day-folders older than IMAGE_RETENTION_DAYS
│     └── saves to ~/images/generated/YYYY-MM-DD/<timestamp>-<uuid8>.png
│     └── returns b64_json (LobeHub compat) OR {"url": ".../v1/images/YYYY-MM-DD/<filename>"}
├── GET  /v1/images/{date}/{filename}   # NEW: serves saved PNG by date/filename
├── GET  /v1/models                     # unchanged
├── GET  /health                        # unchanged
└── /mcp  (mounted FastMCP app)         # NEW: Streamable HTTP MCP server
      └── tool: generate_image(prompt, model, size)
            → triggers cleanup + generation
            → returns "http://localhost:8082/v1/images/YYYY-MM-DD/<timestamp>-<uuid8>"
```

## TDD Workflow (London School, per increment)

Each code increment follows this exact loop:

1. **Stubs** — I write function/method signatures only (raise `NotImplementedError` or `...`), no implementation
2. **Red agent** — subagent writes failing tests (mocks at the boundary, asserts on behaviour)
3. **WIP commit** — `git commit -m "wip: red <increment>"`
4. **Green agent** — separate subagent writes implementation to make tests pass (must not touch test files)
5. **WIP commit** — `git commit -m "wip: green <increment>"`
6. **Verify** — I diff test files between red and green commits; if tests changed → reject, fix, retry
7. **Clean commit** — squash/replace WIP commits with a proper commit message

### Increments (Code phase order)

| # | Increment | Stubs in |
|---|-----------|----------|
| 1 | `make_image_filename()` + `cleanup_old_images()` — pure utility functions | `bridge.py` |
| 2 | `save_image_to_disk()` — write bytes to date/filename path, return relative path | `bridge.py` |
| 3 | `wait_for_prompt_async()` — async wrapper around ComfyUI polling | `bridge.py` |
| 4 | `GET /v1/images/{date}/{filename}` — serve saved PNG | `bridge.py` |
| 5 | Refactor `generate_images()` — WORKFLOW_DIR, save to disk, cleanup, async polling | `bridge.py` |
| 6 | `generate_image` MCP tool — FastMCP mount, calls shared generation logic | `bridge.py` |

### Test conventions

- Framework: `pytest` + `pytest-asyncio`
- Mocks: `unittest.mock` (`patch`, `AsyncMock`) — mock at I/O boundaries (filesystem, `requests`, ComfyUI HTTP)
- London school: test *interactions* (what was called, with what) not just return values
- No real filesystem writes, no real HTTP calls in unit tests
- Test file: `comfyui-bridge/test_bridge.py`

## Notes

### Service Ports (unchanged)

| Port | Service |
|------|---------|
| 8080 | llama-server (default) |
| 8081 | whisper-server |
| 8082 | comfyui bridge (OpenAI image API + MCP server) |
| 8188 | ComfyUI native UI |

### OpenCode MCP config (how to wire it up)

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

### Backward compatibility

- `POST /v1/images/generations` with `response_format=b64_json` still works (LobeHub)
- When `response_format` is not `b64_json`, the response will include a URL instead
- `WORKFLOW_FILE` env var removed; `WORKFLOW_DIR` replaces it
- `comfyui-server-container` is the only caller of `WORKFLOW_FILE` → updated together

## Explore
<!-- beads-phase-id: local-ai-1.1 -->
### Tasks
<!-- beads-synced: 2026-06-01 -->
*Auto-synced — do not edit here, use `bd` CLI instead.*


## Plan
<!-- beads-phase-id: local-ai-1.2 -->
### Tasks
<!-- beads-synced: 2026-06-01 -->
*Auto-synced — do not edit here, use `bd` CLI instead.*

- [x] `local-ai-1.2.1` Refactor bridge.py: WORKFLOW_FILE → WORKFLOW_DIR + dynamic model selection
- [x] `local-ai-1.2.10` Create docs/adr/04-mcp-image-tool.md
- [x] `local-ai-1.2.11` Update root README.md with MCP endpoint and new GET /v1/images/{id}
- [x] `local-ai-1.2.12` Add date-based image storage, on-generation TTL cleanup (replaces systemd timer approach)
- [x] `local-ai-1.2.13` Lock in TDD London School workflow and increment order in plan file
- [x] `local-ai-1.2.2` Add image persistence: save PNG to ~/images/generated/<uuid>.png + GET /v1/images/{id} endpoint
- [x] `local-ai-1.2.3` Async-safe polling: wrap sync requests/polling loop in asyncio.to_thread()
- [x] `local-ai-1.2.4` Integrate FastMCP: mount MCP server at /mcp with generate_image tool
- [x] `local-ai-1.2.5` Create comfyui-bridge/requirements.txt
- [x] `local-ai-1.2.6` Update comfyui-server-container: use WORKFLOW_DIR, remove preset arg requirement
- [x] `local-ai-1.2.7` Update comfyui-server host wrapper: pass WORKFLOW_DIR, sync bridge changes
- [x] `local-ai-1.2.8` Create systemd/image-cleanup.timer and image-cleanup.service
- [x] `local-ai-1.2.9` Update systemd/README.md with cleanup units and MCP info

## Code
<!-- beads-phase-id: local-ai-1.3 -->
### Tasks
<!-- beads-synced: 2026-06-01 -->
*Auto-synced — do not edit here, use `bd` CLI instead.*

- [x] `local-ai-1.3.1` Create comfyui-bridge/requirements.txt and requirements-dev.txt
- [x] `local-ai-1.3.10` Refactor: move MCP tool to mcp_tools.py, routes to routes.py
- [x] `local-ai-1.3.11` Update tests for refactored structure
- [x] `local-ai-1.3.12` Deploy and verify
- [x] `local-ai-1.3.2` Update comfyui-server-container: WORKFLOW_FILE -> WORKFLOW_DIR, no preset arg required
- [x] `local-ai-1.3.3` Update comfyui-server host wrapper: WORKFLOW_DIR, no per-preset workflow file arg
- [x] `local-ai-1.3.4` Update systemd/README.md: document MCP endpoint, comfyui section
- [x] `local-ai-1.3.5` Update README.md: document MCP endpoint, WORKFLOW_DIR, new GET /v1/images endpoint
- [x] `local-ai-1.3.6` Create docs/adr/04-mcp-image-tool.md
- [x] `local-ai-1.3.7` Squash WIP commits into clean commit
- [x] `local-ai-1.3.8` Remove cache busting from bridge.py
- [x] `local-ai-1.3.9` Update MCP tool: width/height params, remove size, hide fixed-AR presets from enum

### Key Decisions (MCP integration fix — post-deploy)

- **Root cause**: `app.mount("/mcp", mcp.streamable_http_app())` silently skips the FastMCP lifespan. FastAPI does NOT propagate lifespan events to mounted sub-apps, so `StreamableHTTPSessionManager.run()` (which initializes the anyio task group) was never called. Every request to `/mcp` returned 307 → `/mcp/` → 404, and direct `/mcp/` returned `RuntimeError: Task group is not initialized`.
- **Fix**: Build `StreamableHTTPSessionManager` + `StreamableHTTPASGIApp` explicitly; start the session manager inside the FastAPI `lifespan=` context manager; register `/mcp` via `app.add_route()` (not `app.mount()`). This matches the pattern documented in `StreamableHTTPSessionManager.run()` docstring.
- **stateless=True**: Used stateless mode — no server-side session state per client. Each request is fully independent. Correct for a single-tool, single-user local server.
- **json_response=True**: Returns JSON body (not SSE stream) for single-request tool calls. MCP Inspector and all standard MCP clients work with both; JSON is simpler for curl debugging.
- **Test note**: The existing 36 tests still pass after the fix (they mock the session manager boundary; they don't test the lifespan wiring which is a deploy-time concern).

### Key Decisions (GREEN + implementation)

- **`load_workflow()` guard**: green agent added a guard for non-Path/str args (returns `{}`) to prevent accidental stdin reads when mocked — harmless production-safe addition
- **`generate_image` MCP tool**: calls `generate_images(req)` directly (shares all logic), parses `JSONResponse.body` to extract URL, wraps all exceptions as `RuntimeError`
- **`list_models` endpoint**: updated to read actual `.json` files from `WORKFLOW_DIR` at request time (dynamic), falls back to hardcoded list if dir empty
- **`comfyui-server`**: no longer requires a preset argument; shows available presets informally then starts; syncs all workflows at once; instance name `@comfyui` (or any name)
- **`comfyui-server-container`**: validates `WORKFLOW_DIR` exists before starting; logs available presets; passes `BRIDGE_BASE_URL`, `IMAGE_DIR`, `IMAGE_RETENTION_DAYS` to bridge
- **Squash**: two WIP commits (`red`, `green`) squashed into one `feat(bridge):` commit with all 9 changed/created files

### Key Decisions (post-deploy enhancements)

- **Seed passthrough**: MCP tool accepts optional `seed: int | None` and always returns the used seed. REST endpoint also returns `"seed"` in the JSON response. Verified: same seed + different size = same motif (composition, lighting, object placement), just different resolution/detail. Pixel-perfect identical when all params match.
- **ComfyUI cache behavior**: identical prompt + model + size + seed returns empty `data: []` because ComfyUI caches the output node (SaveImage) and skips re-execution. Agents must change at least one param (width, height, model, prompt) when re-using a seed.
- **Structured output**: MCP tool returns `ImageGenerationResult(BaseModel)` with `.url` and `.seed` fields instead of a plain string. FastMCP auto-generates a proper `outputSchema: {properties: {url: {type: string}, seed: {type: integer}}, required: [url, seed], type: object}`. Agents get clean JSON, not string parsing.
- **MCP tool params**: replaced combined `size: "WxH"` with separate `width: int` and `height: int` (defaults 1024, min 64, max 2048). Model enum reduced to `flux-dev` and `flux-dev-fast` only — fixed-AR presets (`flux-dev-3-2`, `flux-dev-2-3`) still accessible via REST API but hidden from MCP enum to avoid confusion.
- **Refactor into 5 files**:
  - `bridge.py` — pure utilities, config, models (no FastAPI, no MCP)
  - `routes.py` — FastAPI REST routes (`/v1/images/generations`, `/v1/images/{date}/{filename}`, `/v1/models`, `/health`)
  - `mcp_tools.py` — MCP tool `generate_image` + `ImageGenerationResult` + `ModelChoice`
  - `main.py` — entry point: creates `FastAPI(app)`, wires MCP lifespan, includes routes
  - `comfyui-bridge.py` — tiny stub for systemd `pkill -f comfyui-bridge.py` compatibility; imports and runs `main.py`
- **routes.py uses module-qualified imports** (`import bridge; bridge.save_image_to_disk(...)`) so tests can continue to patch `bridge.X` and the patch propagates to route handlers.
- **Test imports updated**: `from main import app`, `from mcp_tools import generate_image` instead of re-exports from `bridge.py` (which would create circular imports).

### Key Decisions (RED phase)

- **Test file location**: `comfyui-bridge/test_bridge.py` (36 tests, 6 increment classes)
- **pytest-asyncio mode**: Default mode used; async tests marked with `@pytest.mark.asyncio`
- **asyncio.coroutine removed in Python 3.14**: Used `side_effect=fake_to_thread` async function pattern instead of the removed `asyncio.coroutine` decorator
- **NotImplementedError IS a subclass of RuntimeError** in Python: The Increment 6 "propagates as RuntimeError" test uses `assert not isinstance(exc_info.value, NotImplementedError)` pattern to distinguish stub failures from real RuntimeError propagation
- **httpx.ASGITransport**: Used `httpx.ASGITransport(app=app)` (not the deprecated `app=app` kwarg) for async FastAPI testing
- **patch target for shutil**: Must patch `bridge.shutil.rmtree` (not `shutil.rmtree`) since bridge imports `shutil` at module level
- **All 36 tests fail** against current stubs with `NotImplementedError` as expected
- **venv created** at `comfyui-bridge/.venv` with: pytest, pytest-asyncio, httpx, fastapi, mcp, requests

## Commit
<!-- beads-phase-id: local-ai-1.4 -->
### Tasks
<!-- beads-synced: 2026-06-01 -->
*Auto-synced — do not edit here, use `bd` CLI instead.*

- [x] `local-ai-1.4.1` Remove debug prints and commented-out code
- [x] `local-ai-1.4.10` Add steps param (default 20) injected into BasicScheduler node
- [x] `local-ai-1.4.11` Stream SSE progress from ComfyUI WebSocket during generation
- [x] `local-ai-1.4.12` Update tests for steps + SSE progress
- [x] `local-ai-1.4.13` Update docs and commit
- [x] `local-ai-1.4.2` Review and address TODO/FIXME comments
- [x] `local-ai-1.4.3` Review documentation for accuracy
- [x] `local-ai-1.4.4` Run final validation (all tests)
- [x] `local-ai-1.4.5` Squash commits if needed and verify branch
- [x] `local-ai-1.4.6` STEP 1: Search and remove debug output statements
- [x] `local-ai-1.4.7` STEP 2: Review TODO/FIXME comments
- [x] `local-ai-1.4.8` STEP 3: Review documentation accuracy vs final implementation
- [x] `local-ai-1.4.9` STEP 4: Run final test validation

### Key Decisions (Commit phase)

- **__pycache__ cleanup**: Removed committed `__pycache__/*.pyc` files and added `comfyui-bridge/__pycache__/` to `.gitignore`
- **Documentation fixes**: Updated README.md, ADR 04, and systemd/README.md to reflect final MCP schema (width/height params, 2-model enum, structured `{url, seed}` output, seed re-use)
- **PR created**: https://github.com/digitaleraluhut/local-ai/pull/3 — branch `feat/tool-call-image-generation` → `main`
- **Commit history squash**: 15 raw WIP commits squashed into 5 logical commits (feat core, fix deploy, feat seed, refactor 5-files, docs) via `git reset --soft main` + staged-by-file recommits
- **steps param added** (post-testing feedback): `steps: int | None` on `ImageGenerationRequest` and the MCP tool. Injected into `BasicScheduler` and `KSampler` nodes by `inject_prompt()`. `None` = use workflow default (20). All workflow JSONs updated to default 20 steps (flux-dev-fast was 8).
- **SSE progress streaming added** (post-testing feedback): `POST /v1/images/generations` with `Accept: text/event-stream` returns `StreamingResponse` with per-step events `{type:progress, step:N, total:M}` and final `{type:result, ...}`. Non-SSE path unchanged (backward compat with LobeHub).
- **WebSocket replaces HTTP polling**: `stream_prompt_progress()` connects to `ws://{COMFYUI_HOST}:{COMFYUI_PORT}/ws` and yields `{type:progress}` / `{type:done}` events from ComfyUI's native WebSocket feed. `wait_for_prompt_async()` drives this stream and fetches history via `GET /history/{id}` after done. Eliminates repeated 0.5s polling and keeps a single live connection during generation.
- **run_generation() extracted**: Shared generation core in `bridge.py` used by both the REST route (non-streaming) and the MCP tool. MCP tool no longer calls `generate_images(req, request)` which required a FastAPI `Request` object.
- **websockets package added** to `requirements.txt`
- **43 tests total** (was 37): added `TestInjectPromptSteps` (4 tests), `TestStreamPromptProgress` (4 tests), updated `TestWaitForPromptAsync` (3 tests, rewritten for WebSocket), updated `TestGenerateImageMcpTool` (4 tests, now mock `bridge.run_generation`)

### Key Decisions (deployment debugging — port conflict crash loop)

- **Root cause**: `comfyui-server@flux-dev.service` (a stale enabled unit from before the instance was renamed to `@comfyui`) was running alongside `comfyui-server@comfyui.service`, both competing for port 8188. `systemctl --user disable --now comfyui-server@flux-dev` resolved the crash loop permanently.
- **pkill glob bug**: `pkill -f "python3? main.py.*--port.*8188"` in ExecStopPost silently never matched. Systemd unit files treat `?` as a shell glob (matches exactly one char), not a regex quantifier. Fixed to `pkill -f "main.py.*--port.*8188"` (process-name prefix dropped; argument pattern is unique enough).
- **websockets missing from container**: `setup-comfyui-container.sh` only installed the original bridge deps. Added `websockets`, `httpx`, `mcp[cli]`, `uvicorn[standard]` and fixed a pre-existing `distribox` → `distrobox` typo on the exec line.
- **Container startup port cleanup**: Added port-based (`fuser -k`) cleanup in `comfyui-server-container` before starting each component. Port-based kill (not name-based) avoids the race where pkill matches the freshly spawned process instead of the orphan.
- **No dynamic pip at runtime**: Deps are installed at container setup time (`setup-comfyui-container.sh`), not at service start.

## Review
<!-- beads-phase-id: local-ai-1.5 -->
### Tasks
<!-- beads-synced: 2026-06-01 -->
*Auto-synced — do not edit here, use `bd` CLI instead.*

