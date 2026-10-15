"""Unit tests for the Monero client.

These drive `MoneroRPC` directly with a fake `urlopen`, pinning both
transports: a JSON-RPC success unwraps `result`, a JSON-RPC error raises with
its code, a root endpoint returns the whole object, a `"status": "Failed"`
endpoint raises, and a restricted-RPC 404 is named as "not available".
"""

from __future__ import annotations

import email.message
import io
import json
import urllib.error

import pytest

import rpc as rpc_module
from rpc import MoneroRPC, RPCError

URL = "http://monerod:18089"


class _Response:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_exc: object) -> bool:
        return False


def _install(monkeypatch, *, body=None, raw=None, error=None, captured=None):
    def fake_urlopen(request, timeout=None):
        if captured is not None:
            captured.append(request)
        if error is not None:
            raise error
        data = raw if raw is not None else json.dumps(body).encode()
        return _Response(data)

    monkeypatch.setattr(rpc_module.urllib.request, "urlopen", fake_urlopen)


def _http_error(code: int, body: bytes = b"") -> urllib.error.HTTPError:
    return urllib.error.HTTPError(URL, code, "err", email.message.Message(), io.BytesIO(body))


def test_json_rpc_success_returns_result(monkeypatch) -> None:
    _install(monkeypatch, body={"result": {"height": 5}, "error": None})
    assert MoneroRPC(URL).json_rpc("get_info") == {"height": 5}


def test_json_rpc_error_raises_with_code(monkeypatch) -> None:
    _install(monkeypatch, body={"result": None, "error": {"code": -32601, "message": "no method"}})
    with pytest.raises(RPCError) as excinfo:
        MoneroRPC(URL).json_rpc("get_info")
    assert excinfo.value.code == -32601
    assert excinfo.value.message == "no method"


def test_endpoint_returns_the_whole_object(monkeypatch) -> None:
    _install(monkeypatch, body={"status": "OK", "missed_tx": ["ab"]})
    assert MoneroRPC(URL).endpoint("/get_transactions") == {"status": "OK", "missed_tx": ["ab"]}


def test_endpoint_failed_status_raises(monkeypatch) -> None:
    _install(monkeypatch, body={"status": "Failed", "error": "bad request"})
    with pytest.raises(RPCError) as excinfo:
        MoneroRPC(URL).endpoint("/get_transactions")
    assert "bad request" in excinfo.value.message


def test_restricted_404_is_named(monkeypatch) -> None:
    _install(monkeypatch, error=_http_error(404))
    with pytest.raises(RPCError) as excinfo:
        MoneroRPC(URL).endpoint("/get_connections")
    assert "not available" in excinfo.value.message


def test_http_401_is_named_as_auth_failure(monkeypatch) -> None:
    _install(monkeypatch, error=_http_error(401))
    with pytest.raises(RPCError) as excinfo:
        MoneroRPC(URL, "user", "pass").json_rpc("get_info")
    assert "authentication" in excinfo.value.message


def test_unreachable_node_is_named(monkeypatch) -> None:
    _install(monkeypatch, error=urllib.error.URLError("connection refused"))
    with pytest.raises(RPCError) as excinfo:
        MoneroRPC(URL).json_rpc("get_info")
    assert "cannot reach the node" in excinfo.value.message


def test_basic_auth_attached_only_with_credentials(monkeypatch) -> None:
    captured: list = []
    _install(monkeypatch, body={"result": 1, "error": None}, captured=captured)

    MoneroRPC(URL).json_rpc("get_info")
    assert captured[-1].get_header("Authorization") is None

    MoneroRPC(URL, "user", "pass").json_rpc("get_info")
    assert captured[-1].get_header("Authorization") == "Basic dXNlcjpwYXNz"
