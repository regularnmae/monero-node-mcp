# What this repo owns, and what it depends on

This repo owns only the **application** — its Python code, tests, CI and
`Containerfile`. It ships no unit and no env file. The runtime is owned by
[`stack`](https://github.com/regularnmae/stack), which holds every quadlet unit
and the `npm-network.network` the MCP servers share, and renders the
`$DATA_DIR/config/<name>/*.env` files. See `stack/deploy/` and
`stack/deploy/examples/monero-node-mcp/`.

It does **not** own `monerod` either. The node's unit is owned by `stack`,
together with the rest of the crypto node stack — one file, one owner. See that
repo to rebuild the node.

## Upstream contract

The server assumes a monerod reachable on the podman network:

| | |
| --- | --- |
| Container / address | `monerod:18089` (JSON-RPC, **restricted RPC**, no host publish) |
| Network | `npm-network` |
| Auth | none (restricted RPC runs without a login) |
| Config | `--prune-blockchain` |

Two consequences shape the tools:

- **Restricted RPC only** serves a subset of methods and answers HTTP 404 for
  the rest (`/get_connections`, `/get_transaction_pool` are not available;
  `/get_info`, `/get_transactions` and `/get_transaction_pool_stats` are).
  Standard RPC (`18081`) is bound to loopback *inside* the container and is not
  reachable at all. Adding a tool for a method the restricted RPC refuses will
  fail at runtime — check first.
- **pruned** — old transaction data may be missing; misses appear in
  `get_transactions`' `missed_tx` rather than as an error.

If a future monerod is started with `--rpc-login`, note monerod uses HTTP
**digest** auth (Basic is rejected) and its nonce is bound to the TCP
connection — the client here sends Basic and would need the same digest-over-one-
connection handling `monero-wallet-mcp` has.

## Deploy

```sh
cd ~/build/stack
./deploy.sh --only monero-node-mcp   # build the image, restart, wait for "(healthy)"
```

Secrets land in `$DATA_DIR/config/monero-node-mcp/`; `./deploy.sh` opens `8102/tcp`
in firewalld.
