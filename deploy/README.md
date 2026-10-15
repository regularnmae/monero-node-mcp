# deploy/ — what this repo owns, and what it depends on

This repo owns exactly **one** unit — `monero-node-mcp.container` — plus a
shared network file:

- `monero-node-mcp.container` — the MCP server, `PublishPort=8102:8000`.
- `npm-network.network` — the podman network it shares with the daemons.
  `install.sh` links it **only if no other repo has already provided it**, so
  deploying this repo cannot fight another one over the same file.

It does **not** own `monerod`. The node's unit is owned by
[`crypto-nodes`](https://github.com/regularnmae/crypto-nodes), together with the
rest of the crypto node stack — one file, one owner. See that repo to rebuild
the node.

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
./deploy/install.sh     # token.env + (usually empty) upstream.env, symlink the unit, reload
./deploy.sh             # install + build + restart + wait healthy
sudo firewall-cmd --permanent --add-port=8102/tcp && sudo firewall-cmd --reload
```

Secrets land in `~/.config/monero-node-mcp/`.
