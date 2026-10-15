# monero-node-mcp — agent notes

Flat three-module Python MCP server (not a package). `server.py` is the app —
config, tools, auth middleware; `rpc.py` is its **stdlib-only** Monero daemon
client; `healthcheck.py` is the container healthcheck probe. Shipped as a
rootless podman/quadlet container, unit under `deploy/`. Toolchain is uv only.
`mcp` is the 2.x line: the app object is `MCPServer` (the v2 rename of
`FastMCP`).

One of four sibling crypto MCP servers (`bitcoin-node-mcp`,
`monero-node-mcp`, `monero-wallet-mcp`, `lightning-mcp`), modelled on the
pre-existing `searxng-mcp`. Env vars, tool list and the security model are in
`README.md`; don't re-derive them from the code.

## Commands

```sh
uv run ruff check .            # lint (CI gate); line-length 100, rules E,F,I,UP,B,SIM
uv run pyright                 # typecheck (CI gate)
uv run pytest -q               # tests, no network
uv run python scripts/smoke.py # boots the real app on a free loopback port
uv add <pkg>                   # edits pyproject.toml AND re-locks
podman build -t localhost/monero-node-mcp:latest .
./deploy.sh                    # builds, restarts monero-node-mcp.service, waits for "(healthy)"
```

## Facts that are easy to get wrong

- **Two transports, one client.** monerod answers `/json_rpc` methods under
  `result`, and root endpoints (`/get_transactions`,
  `/get_transaction_pool_stats`) with the object itself. `rpc.py` exposes
  `json_rpc()` and `endpoint()`; tools pick the right one.
- **Only the restricted RPC (18089) is reachable.** Standard RPC (18081) is
  loopback-inside-the-container. The restricted surface 404s for methods it
  does not serve (`/get_connections`, `/get_transaction_pool`); that is
  surfaced as "not available", not hidden. Do not add tools for methods the
  restricted RPC refuses without checking first.
- `get_block` **trims the raw `blob`** on purpose — returning it would dump
  megabytes. Keep the trimming if you touch that tool.
- Unlike bitcoind, monerod pruning does **not** block `get_block` for old
  heights (headers and miner txs are kept); old *transaction* data can still
  be missing, which shows up in `get_transactions`' `missed_tx`.
- `rpc.py` raises one exception type, `RPCError`, for a JSON-RPC error, a
  `"status":"Failed"` endpoint, an HTTP status and a transport failure.
- Tool bodies are synchronous (`def`); anyio runs them on worker threads.
- Every `@mcp.tool` passes `structured_output=False` and
  `annotations=_NODE_TOOLS`; `tests/test_schemas.py` pins the exact tool set —
  adding a tool means updating `TOOLS` there.
- Numeric args bounded with `Annotated[int, Field(ge=…)]`; a nullable one is
  `Annotated[int, Field(ge=0)] | None` and renders as an `anyOf`.
- A new top-level module must go in the `Containerfile`'s `COPY` lines **and**
  pyright's `include`.
- The image declares no `HEALTHCHECK`; the quadlet supplies
  `HealthCmd=python /app/healthcheck.py` plus `MONERO_MCP_TOKEN`.
- Publishing: `PublishPort=8102:8000`. Open `8102/tcp` in firewalld.
- `deploy/install.sh` writes `~/.config/monero-node-mcp/{token,upstream}.env`
  (mode 600) and symlinks the unit; `npm-network.network` is linked only if no
  other repo already provided it.

## Testing quirks

- Tests use the SDK's in-memory `Client(mcp)`; no sockets. `fake_rpc` replaces
  `server.rpc.json_rpc` and `server.rpc.endpoint` with a scripted fake that
  records calls, so parameter shaping and transport choice are pinned.
- `pytest` runs with `pythonpath = ["."]`; `import server` / `import rpc`
  work as top-level modules. Do **not** `from conftest import ...` in a test —
  `tests` is a package and that import fails.
