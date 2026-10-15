"""Minimal client for a Monero daemon (monerod).

Stdlib-only on purpose: this server only POSTs JSON to one daemon on the
podman network, so it needs neither a redirect-following client nor a TLS
stack, and the smaller closure is less to audit.

monerod speaks two shapes and this client covers both:

- JSON-RPC 2.0 on `/json_rpc` -- `get_info`, `get_block`, `get_block_count`
  and friends, where the answer is under `result`;
- plain POST endpoints at the root -- `/get_transactions`,
  `/get_transaction_pool_stats` -- where the answer is the object itself and
  a failure carries `"status": "Failed"`.

Both raise the one `RPCError`, so a tool body has a single thing to catch.
The restricted RPC port (`--rpc-restricted-bind-port`) serves only a subset
of methods and answers HTTP 404 for the rest; that is surfaced as an
`RPCError`, not hidden.
"""

import base64
import json
import urllib.error
import urllib.request
from typing import Any

DEFAULT_TIMEOUT = 30.0


class RPCError(Exception):
    """A failed RPC call.

    `message` is the daemon's human-readable text; `code` is Monero's
    numeric error code when the daemon supplied one, or None for a
    transport failure or a plain HTTP status.
    """

    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def _error_code(error: dict[str, Any]) -> int | None:
    code = error.get("code")
    return code if isinstance(code, int) else None

class MoneroRPC:
    """A client bound to one monerod endpoint (e.g. http://monerod:18089)."""

    def __init__(
        self,
        url: str,
        user: str = "",
        password: str = "",
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._url = url.rstrip("/")
        self._timeout = timeout
        # The restricted RPC usually runs with no login; attach Basic auth
        # only when credentials are configured.
        if user or password:
            raw = f"{user}:{password}".encode()
            self._auth = "Basic " + base64.b64encode(raw).decode()
        else:
            self._auth = ""

    def json_rpc(self, method: str, params: dict[str, Any] | None = None) -> Any:
        """Invoke a `/json_rpc` method, returning its `result`."""
        body = {"jsonrpc": "2.0", "id": "0", "method": method, "params": params or {}}
        parsed = self._post("/json_rpc", body)
        if parsed.get("error"):
            raise RPCError(
                str(parsed["error"].get("message", "rpc error")),
                _error_code(parsed["error"]),
            )
        return parsed.get("result")

    def endpoint(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """POST a root endpoint, returning the whole response object."""
        parsed = self._post(path, params or {})
        if str(parsed.get("status", "")).lower() == "failed":
            error = parsed.get("error")
            if isinstance(error, dict):
                raise RPCError(
                    str(error.get("message", "request failed")), _error_code(error)
                )
            text = str(error or parsed.get("reason") or "request failed")
            raise RPCError(text)
        return parsed

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        payload = json.dumps(body).encode()
        headers = {"Content-Type": "application/json"}
        if self._auth:
            headers["Authorization"] = self._auth
        request = urllib.request.Request(
            self._url + path, data=payload, headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                parsed = _decode(response.read())
        except urllib.error.HTTPError as err:
            parsed = _decode(err.read())
            if parsed is not None and parsed.get("error"):
                raise RPCError(
                    str(parsed["error"].get("message", "rpc error")),
                    _error_code(parsed["error"]),
                ) from err
            if err.code == 401:
                raise RPCError(
                    "authentication to the node failed "
                    "(check MONERO_RPC_USER / MONERO_RPC_PASSWORD)"
                ) from err
            if err.code == 404:
                raise RPCError(
                    f"method not available on this RPC endpoint (HTTP 404): {path}. "
                    "The restricted RPC serves only a subset of methods."
                ) from err
            raise RPCError(f"HTTP {err.code} from the node") from err
        except urllib.error.URLError as err:
            raise RPCError(f"cannot reach the node at {self._url}: {err.reason}") from err
        if parsed is None:
            raise RPCError(f"the node returned a non-JSON body for {path}")
        return parsed


def _decode(raw: bytes) -> dict[str, Any] | None:
    """Parse a JSON object from a response body, or None if it is not one."""
    try:
        parsed = json.loads(raw.decode(errors="replace"))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None
