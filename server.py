import hmac
import json
import logging
import os
from typing import Annotated, Any, Literal, get_args

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import Field

from rpc import MoneroRPC, RPCError

logger = logging.getLogger("monero-node-mcp")

_LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
_LEVELS: tuple[_LogLevel, ...] = get_args(_LogLevel)


def _log_level() -> _LogLevel:
    requested = os.environ.get("LOG_LEVEL", "INFO").upper()
    return requested if requested in _LEVELS else "INFO"


def _env_float(name: str, default: float) -> float:
    """A float env var, or the default when unset or unparseable."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("ignoring non-numeric %s=%r; using %s", name, raw, default)
        return default


mcp = MCPServer(
    "Monero Node",
    instructions=(
        "Read-only access to this host's Monero daemon (monerod) over its "
        "restricted RPC. Start with get_info for height, sync state and "
        "target height. This is a node, not a wallet: nothing here sees keys "
        "or moves funds. The restricted RPC serves only a subset of methods, "
        "so some calls may answer that a method is unavailable."
    ),
    log_level=_log_level(),
)

# Every tool here only reads. Saying so lets a well-behaved client skip a
# confirmation prompt before running one of them. A node is open-world:
# its answers depend on the state of the network it is following.
_NODE_TOOLS = ToolAnnotations(read_only_hint=True, open_world_hint=True)

# Reached over the podman npm-network (container name resolves without any
# host publishing); MONERO_RPC_URL overrides. 18089 is monerod's restricted
# RPC port; the standard RPC (18081) is bound to loopback inside the
# container and is not reachable from the network.
MONERO_RPC_URL = os.environ.get("MONERO_RPC_URL", "http://monerod:18089")
MONERO_RPC_USER = os.environ.get("MONERO_RPC_USER", "")
MONERO_RPC_PASSWORD = os.environ.get("MONERO_RPC_PASSWORD", "")
RPC_TIMEOUT = _env_float("MONERO_RPC_TIMEOUT", 30.0)

MCP_ALLOW_ANONYMOUS = os.environ.get("MCP_ALLOW_ANONYMOUS", "") == "1"
HEALTH_PATH = "/health"
TOKEN_ENV = "MONERO_MCP_TOKEN"

rpc = MoneroRPC(MONERO_RPC_URL, MONERO_RPC_USER, MONERO_RPC_PASSWORD, timeout=RPC_TIMEOUT)


def _render(result: Any) -> str:
    """A tool result as text: a bare string as-is, anything else as JSON."""
    if isinstance(result, str):
        return result
    return json.dumps(result, indent=2)


def _error_text(err: RPCError) -> str:
    if err.code is None:
        return err.message
    return f"{err.message} (RPC error {err.code})"


def _call(method: str, params: dict[str, Any] | None = None) -> str:
    """Run one JSON-RPC method and render the result, or a readable error."""
    try:
        return _render(rpc.json_rpc(method, params))
    except RPCError as err:
        logger.warning("%s failed: %s", method, err.message)
        return _error_text(err)
    except Exception as err:  # noqa: BLE001 - surfaced as text, never hidden
        logger.exception("unexpected error in %s", method)
        return f"Unexpected error calling {method}: {err}"


@mcp.tool(structured_output=False, annotations=_NODE_TOOLS)
def get_info() -> str:
    """Return the node's state.

    Includes height, target height, sync status, difficulty, transaction
    pool size, database size and version -- the first call to make.
    """
    return _call("get_info")


@mcp.tool(structured_output=False, annotations=_NODE_TOOLS)
def get_block_count() -> str:
    """Return the number of blocks in the longest chain."""
    return _call("get_block_count")


@mcp.tool(structured_output=False, annotations=_NODE_TOOLS)
def get_last_block_header() -> str:
    """Return the most recent block's header."""
    return _call("get_last_block_header")


@mcp.tool(structured_output=False, annotations=_NODE_TOOLS)
def get_block_header_by_height(height: Annotated[int, Field(ge=0)]) -> str:
    """Return a block header by height.

    Args:
        height: Block height, 0 for the genesis block.
    """
    return _call("get_block_header_by_height", {"height": height})


@mcp.tool(structured_output=False, annotations=_NODE_TOOLS)
def get_block_header_by_hash(block_hash: str) -> str:
    """Return a block header by block hash.

    Args:
        block_hash: Block hash (hex).
    """
    return _call("get_block_header_by_hash", {"hash": block_hash})


@mcp.tool(structured_output=False, annotations=_NODE_TOOLS)
def get_block(
    height: Annotated[int, Field(ge=0)] | None = None, block_hash: str = ""
) -> str:
    """Return a block's header and decoded contents.

    Give exactly one of `height` or `block_hash`. The raw block blob is
    omitted, since it is large and the decoded form carries the same data.

    Args:
        height: Block height.
        block_hash: Block hash (hex); use instead of height.
    """
    if (height is None) == (not block_hash):
        return "Provide exactly one of `height` or `block_hash`."
    params: dict[str, Any] = (
        {"height": height} if height is not None else {"hash": block_hash}
    )
    try:
        result = rpc.json_rpc("get_block", params)
    except RPCError as err:
        logger.warning("get_block failed: %s", err.message)
        return _error_text(err)
    except Exception as err:  # noqa: BLE001 - surfaced as text, never hidden
        logger.exception("unexpected error in get_block")
        return f"Unexpected error calling get_block: {err}"
    trimmed = {
        "block_header": result.get("block_header"),
        "json": result.get("json"),
        "tx_hashes": result.get("tx_hashes"),
    }
    return _render(trimmed)


@mcp.tool(structured_output=False, annotations=_NODE_TOOLS)
def get_version() -> str:
    """Return the daemon's version."""
    return _call("get_version")


@mcp.tool(structured_output=False, annotations=_NODE_TOOLS)
def get_fee_estimate(grace_blocks: Annotated[int, Field(ge=0)] = 10) -> str:
    """Return a fee estimate for inclusion within a number of blocks.

    Args:
        grace_blocks: Number of blocks within which to be included
            (default 10).
    """
    return _call("get_fee_estimate", {"grace_blocks": grace_blocks})


@mcp.tool(structured_output=False, annotations=_NODE_TOOLS)
def get_transactions(txids: list[str], decode_as_json: bool = False) -> str:
    """Return transactions by id.

    Ids that are not found are listed in the response's `missed_tx` rather
    than raising.

    Args:
        txids: Transaction hashes (hex) to look up.
        decode_as_json: Also return each transaction decoded (can be large;
            default False).
    """
    try:
        return _render(
            rpc.endpoint(
                "/get_transactions",
                {"txs_hashes": txids, "decode_as_json": decode_as_json},
            )
        )
    except RPCError as err:
        logger.warning("get_transactions failed: %s", err.message)
        return _error_text(err)
    except Exception as err:  # noqa: BLE001 - surfaced as text, never hidden
        logger.exception("unexpected error in get_transactions")
        return f"Unexpected error calling get_transactions: {err}"


@mcp.tool(structured_output=False, annotations=_NODE_TOOLS)
def get_transaction_pool_stats() -> str:
    """Return statistics about the node's transaction pool."""
    try:
        return _render(rpc.endpoint("/get_transaction_pool_stats"))
    except RPCError as err:
        logger.warning("get_transaction_pool_stats failed: %s", err.message)
        return _error_text(err)
    except Exception as err:  # noqa: BLE001 - surfaced as text, never hidden
        logger.exception("unexpected error in get_transaction_pool_stats")
        return f"Unexpected error calling get_transaction_pool_stats: {err}"


class BearerAuthMiddleware:
    """Pure-ASGI bearer auth in front of the streamable-HTTP app.

    The endpoint is published on the LAN, so a missing token is a hard
    error rather than a warning. Set MCP_ALLOW_ANONYMOUS=1 to run it open
    on purpose, which is what debugging from inside npm-network wants.

    GET /health stays unauthenticated so a poller can say "up" without
    holding the token; it says nothing else.
    """

    def __init__(self, app: Any, token: str | None) -> None:
        self.app = app
        self.token = token or ""
        if not self.token:
            if not MCP_ALLOW_ANONYMOUS:
                raise RuntimeError(
                    f"{TOKEN_ENV} is not set, and this endpoint is published "
                    "on the LAN. Set the token, or set MCP_ALLOW_ANONYMOUS=1 "
                    "to serve without authentication."
                )
            logger.warning(
                "%s not set and MCP_ALLOW_ANONYMOUS=1: endpoint is UNAUTHENTICATED",
                TOKEN_ENV,
            )

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if scope.get("path") == HEALTH_PATH:
            from starlette.responses import JSONResponse

            response = JSONResponse({"status": "ok"})
            await response(scope, receive, send)
            return

        if self.token and not self._authorised(scope):
            from starlette.responses import JSONResponse

            response = JSONResponse({"error": "unauthorized"}, status_code=401)
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)

    def _authorised(self, scope: Any) -> bool:
        """Compare the presented credential in constant time."""
        headers = dict(scope.get("headers") or [])
        header = headers.get(b"authorization", b"").decode("latin-1").strip()
        scheme, _, presented = header.partition(" ")
        if scheme.lower() != "bearer":
            return False
        return hmac.compare_digest(presented.strip().encode(), self.token.encode())


if __name__ == "__main__":
    import uvicorn

    app = BearerAuthMiddleware(
        mcp.streamable_http_app(
            transport_security=TransportSecuritySettings(
                enable_dns_rebinding_protection=False
            )
        ),
        os.environ.get(TOKEN_ENV),
    )

    uvicorn.run(
        app,
        host=os.environ.get("MCP_HOST", "0.0.0.0"),
        port=int(os.environ.get("MCP_PORT", "8000")),
    )
