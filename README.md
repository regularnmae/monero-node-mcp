# monero-node-mcp

A [Model Context Protocol](https://modelcontextprotocol.io) server that gives
a client read-only access to a Monero node (`monerod`) over JSON-RPC. This is
a *node* server: it sees no keys and moves no funds. It shares the podman
`npm-network` with the node and reaches it by container name.

Ten tools, all read-only:

| Tool | What it does |
| --- | --- |
| `get_info` | Height, target height, sync status, difficulty, pool size, version |
| `get_block_count` | Number of blocks in the longest chain |
| `get_last_block_header` | The most recent block header |
| `get_block_header_by_height` | A block header by height |
| `get_block_header_by_hash` | A block header by block hash |
| `get_block` | A block by height or hash (raw blob omitted) |
| `get_version` | The daemon's version |
| `get_fee_estimate` | A fee estimate for a confirmation window |
| `get_transactions` | Transactions by id (misses returned in `missed_tx`) |
| `get_transaction_pool_stats` | Transaction-pool statistics |

Each tool returns text — a scalar as-is, an object as pretty-printed JSON.
They are all marked read-only and open-world, so a well-behaved client skips
the confirmation prompt.

## The restricted RPC

This server is pointed at monerod's **restricted RPC** (`18089`), which serves
only a subset of methods and answers HTTP 404 for the rest — for example
`/get_connections` and `/get_transaction_pool` are not available, while
`/get_info`, `/get_transactions` and `/get_transaction_pool_stats` are. The
client surfaces a 404 as a plain "method not available on this RPC endpoint"
message rather than a raw status.

Reaching the restricted port is deliberate: the standard RPC port (`18081`) is
bound to loopback inside the container and is not on the network at all, and
the restricted surface is smaller.

`get_block` trims the raw block `blob` (which is large) and returns the
header, the decoded body and the tx hashes.

## Running it

```sh
uv sync
MONERO_MCP_TOKEN=<a long random token> uv run python server.py
```

Or, inside the container:

```sh
podman build -t localhost/monero-node-mcp:latest .
podman run -e MONERO_MCP_TOKEN=<token> -p 8102:8000 localhost/monero-node-mcp:latest
```

It listens on `0.0.0.0:8000` and serves streamable HTTP at `/mcp`. `GET
/health` is unauthenticated and answers `{"status":"ok"}`.

### Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `MONERO_RPC_URL` | `http://monerod:18089` | The node's restricted RPC endpoint |
| `MONERO_RPC_USER` / `MONERO_RPC_PASSWORD` | – | Optional; only if the node uses `--rpc-login` |
| `MONERO_RPC_TIMEOUT` | `30` | RPC timeout in seconds |
| `MONERO_MCP_TOKEN` | – | Bearer token. **Required** unless `MCP_ALLOW_ANONYMOUS=1` |
| `MCP_HOST` / `MCP_PORT` | `0.0.0.0` / `8000` | Listen address |
| `MCP_ALLOW_ANONYMOUS` | – | Set to `1` to serve with no token (loud warning) |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `MONERO_MCP_URL` | `http://127.0.0.1:8000/mcp` | Where `healthcheck.py` probes |

Without `MONERO_MCP_TOKEN` the server refuses to start rather than serving
unauthenticated.

## Security model

This container shares `npm-network` with `bitcoind`, `monerod`,
`monero-wallet-rpc`, `lightningd` and the rest of the stack, and publishes
`8102` on the LAN. It is the least dangerous member of that stack: it speaks
only to monerod's restricted RPC, and only read methods. A prompt-injected
client cannot reach a wallet through it.

The bearer token gates every request except `/health`, compared in constant
time; startup fails without one unless `MCP_ALLOW_ANONYMOUS=1`.

## Development

```sh
uv run pytest -q                # tests, no network
uv run ruff check .             # lint
uv run pyright                  # typecheck
uv run python scripts/smoke.py  # boots the real app on loopback
uv add <package>                # edits pyproject.toml, then re-locks
```

`rpc.py` is stdlib-only on purpose, so the closure is just `mcp` + `uvicorn`.
`tests/test_rpc.py` drives it with a fake `urlopen`; `tests/test_tools.py`
drives each tool against a scripted fake node.

### Adding a tool

```python
@mcp.tool(structured_output=False, annotations=_NODE_TOOLS)
def my_tool(height: Annotated[int, Field(ge=0)]) -> str:
    """What the model sees. Args: ..."""
    return _call("get_block_header_by_height", {"height": height})
```

Add the name to `TOOLS` in `tests/test_schemas.py` — that test pins the exact
tool set.

## Deploying

The runtime for this server — its quadlet unit and env wiring — is owned by the
separate [`stack`](https://github.com/regularnmae/stack) repo, not here:

```sh
cd ~/build/stack
./deploy.sh --only monero-node-mcp   # build the image, restart, wait for "(healthy)"
./deploy.sh                          # the whole stack
```

`stack/deploy.sh` opens `8102/tcp` in firewalld on a fresh host.
`stack/deploy/install.sh` is idempotent. It writes the bearer token to
`$DATA_DIR/config/monero-node-mcp/token.env` (mode 600), reusing the running
container's token, and seeds a usually-empty `upstream.env` for optional RPC
credentials. The unit reads both via `EnvironmentFile=`. The env-file shapes
are documented in `stack/deploy/examples/monero-node-mcp/`. No secret is
committed.
