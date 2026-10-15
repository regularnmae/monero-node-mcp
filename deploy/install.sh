#!/usr/bin/env bash
# Install the quadlet unit for the Monero Node MCP server.
#
# Symlinks this repo's deploy/ unit into the user quadlet directory and
# reloads systemd, so the checkout is the single source of truth. Also seeds
# the bearer-token env file and an (usually empty) upstream-credentials file.
#
# Idempotent: re-running refreshes the symlink and leaves existing env files
# untouched. No secret is committed or printed.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY_DIR="$REPO_DIR/deploy"
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
QUADLET_DIR="$CONFIG_HOME/containers/systemd"
ENV_DIR="$CONFIG_HOME/monero-node-mcp"
TOKEN_FILE="$ENV_DIR/token.env"
UPSTREAM_FILE="$ENV_DIR/upstream.env"

UNITS=(monero-node-mcp.container)

log() { printf '==> %s\n' "$*"; }

rand_hex() {
    openssl rand -hex 32 2>/dev/null && return 0
    head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n'
}

write_secret() {
    local path="$1"
    local old_umask
    old_umask=$(umask)
    umask 077
    cat > "$path"
    umask "$old_umask"
    chmod 600 "$path"
}

mkdir -p "$ENV_DIR"

# 1. bearer token ---------------------------------------------------------
if [ -s "$TOKEN_FILE" ]; then
    log "token env present: $TOKEN_FILE"
else
    token=""
    if command -v podman >/dev/null 2>&1; then
        token=$(podman exec monero-node-mcp printenv MONERO_MCP_TOKEN 2>/dev/null || true)
    fi
    if [ -n "$token" ]; then
        log "reused the existing bearer token"
    else
        token=$(rand_hex)
        log "generated a new bearer token -- update clients to match"
    fi
    write_secret "$TOKEN_FILE" <<EOF
MONERO_MCP_TOKEN=$token
EOF
    log "wrote $TOKEN_FILE (mode 600)"
fi

# 2. upstream RPC credentials --------------------------------------------
# monerod's restricted RPC usually runs with no login, so these are empty by
# default and the client simply omits Basic auth. Set them only if the node
# was started with --rpc-login.
if [ -s "$UPSTREAM_FILE" ]; then
    log "upstream env present: $UPSTREAM_FILE"
else
    write_secret "$UPSTREAM_FILE" <<EOF
# Upstream credentials for the Monero node this server reads. Empty unless
# monerod was started with --rpc-login. The unit reads this via
# EnvironmentFile.
MONERO_RPC_USER=
MONERO_RPC_PASSWORD=
EOF
    log "wrote $UPSTREAM_FILE (mode 600)"
fi

# 3. symlink units into the quadlet search path ---------------------------
mkdir -p "$QUADLET_DIR"

NETWORK_TARGET="$QUADLET_DIR/npm-network.network"
if [ ! -e "$NETWORK_TARGET" ]; then
    ln -sfn "$DEPLOY_DIR/npm-network.network" "$NETWORK_TARGET"
    log "linked npm-network.network"
else
    log "npm-network.network already present"
fi

for unit in "${UNITS[@]}"; do
    target="$QUADLET_DIR/$unit"
    if [ -e "$target" ] && [ ! -L "$target" ]; then
        mv -f "$target" "$target.bak"
        log "backed up existing $unit -> $unit.bak"
    fi
    ln -sfn "$DEPLOY_DIR/$unit" "$target"
    log "linked $unit"
done

if command -v systemctl >/dev/null 2>&1; then
    systemctl --user daemon-reload
    log "systemd --user reloaded"
fi

cat <<EOF

Done. Next:
  ./deploy.sh                                   # install, build, restart, wait healthy
  # or, units only:
  systemctl --user start monero-node-mcp.service

Open the published port on the LAN:
  sudo firewall-cmd --permanent --add-port=8102/tcp && sudo firewall-cmd --reload

Clients must send the bearer token from
  $TOKEN_FILE
as \`Authorization: Bearer <token>\`, pointed at
  http://<host>:8102/mcp
EOF
