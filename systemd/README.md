# Systemd User Services

Parameterized service templates for auto-starting models on boot.

## LLM — llama-server

```bash
cp llama-server@.service ~/.config/systemd/user/
cp -r llama-server@fork-router.service.d ~/.config/systemd/user/
systemctl --user daemon-reload
# Default serving: q38rocm fork (fp4 MTP + bge-m3) on port 8080.
systemctl --user enable --now llama-server@fork-router
```

### Usage

```bash
systemctl --user start llama-server@<config-name>
systemctl --user stop llama-server@<config-name>
systemctl --user status llama-server@<config-name>
```

The instance name matches a config filename in `configs/` (without `.conf`).

## Image Generation — comfyui-server

Single instance — the bridge serves all workflow presets from one process.
The `model` field in each API request selects the workflow at runtime.

```bash
cp llama-server@.service ~/.config/systemd/user/
cp -r llama-server@fork-router.service.d ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now llama-server@fork-router   # active default: fork (fp4 + bge-m3, :8080)
```

Only one instance may own a port at a time. Swap the active preset:

```bash
systemctl --user disable --now llama-server@fork-router
systemctl --user enable --now llama-server@qwen3.6-35b-a3b   # stock MoE lane
# every preset in configs/ is launchable this way (incl. qwen3.8-27b-stock, router, ...)
```

The instance name is arbitrary (used only to distinguish units); it is not a preset name.

### Endpoints (port 8082)

| Endpoint | Description |
|----------|-------------|
| `POST /v1/images/generations` | OpenAI-compatible image generation (LobeHub, curl) |
| `GET /v1/images/{date}/{filename}` | Serve a previously generated image as `image/png` |
| `GET /v1/models` | List available workflow presets |
| `GET /health` | Bridge + ComfyUI health check |
| `POST /mcp` | MCP Streamable HTTP transport (tool: `generate_image`) |

### MCP tool (OpenCode / agent frameworks)

The bridge exposes a `generate_image` MCP tool via Streamable HTTP at `http://localhost:8082/mcp`.
Add to your OpenCode config:

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

Tool schema:

```json
{
  "name": "generate_image",
  "parameters": {
    "prompt": "string (required)",
    "model": "flux-dev | flux-dev-fast (default: flux-dev-fast)",
    "width": "integer, 64-2048 (default: 1024)",
    "height": "integer, 64-2048 (default: 1024)",
    "steps": "integer, 1-150 | null — sampling steps; null uses workflow default (20)",
    "seed": "integer | null — omit or null for random; always returned in result"
  }
}
```

Returns: `{ "url": "http://localhost:8082/v1/images/YYYY-MM-DD/<timestamp>-<uuid8>.png", "seed": <int> }`

### SSE progress streaming (REST)

Add `Accept: text/event-stream` to `POST /v1/images/generations` to receive
Server-Sent Events while generation is running. Clients that would otherwise
time out on a long generation can use this to stay connected:

```
data: {"type": "progress", "step": 5, "total": 20}
data: {"type": "progress", "step": 10, "total": 20}
...
data: {"type": "result", "data": [...], "seed": 42, "created": 1234567890}
```

On error: `data: {"type": "error", "message": "..."}`.
The MCP tool always uses the non-streaming path internally (no client timeout issue
since it drives a WebSocket connection to ComfyUI directly).

### Image storage

Generated images are stored in `~/images/generated/YYYY-MM-DD/` as
`<YYYYMMDDTHHmmSS>-<uuid8>.png` files. Day-folders older than
`IMAGE_RETENTION_DAYS` (default: 7) are removed automatically at the
start of each generation call — no cleanup timers needed.
