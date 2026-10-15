"""Shared fixtures.

Every test talks to the server through the SDK's in-memory client, so no
test opens a socket. The daemon is replaced by `fake_rpc`, which records the
calls a tool made and answers from a per-method script -- the tools, their
parameter shaping and their error handling are what is under test, not
monerod.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest
from mcp import Client

import server


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def client() -> AsyncIterator[Client]:
    """An in-memory client connected to the real server object."""
    async with Client(server.mcp, raise_exceptions=True) as c:
        yield c


class FakeRPC:
    """Stands in for `server.rpc`.

    `json_rpc_answers` / `endpoint_answers` map a method or path to the
    result to return, an exception to raise, or a callable taking the
    params. Anything unscripted answers with a recognisable echo.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []
        self.json_rpc_answers: dict[str, Any] = {}
        self.endpoint_answers: dict[str, Any] = {}

    def _answer(self, answers: dict[str, Any], key: str, params: Any) -> Any:
        answer = answers.get(key)
        if isinstance(answer, Exception):
            raise answer
        if callable(answer):
            return answer(params)
        if answer is None:
            return {"key": key, "params": params}
        return answer

    def json_rpc(self, method: str, params: Any = None) -> Any:
        self.calls.append(("json_rpc", method, params))
        return self._answer(self.json_rpc_answers, method, params)

    def endpoint(self, path: str, params: Any = None) -> Any:
        self.calls.append(("endpoint", path, params))
        return self._answer(self.endpoint_answers, path, params)


@pytest.fixture
def fake_rpc(monkeypatch: pytest.MonkeyPatch) -> FakeRPC:
    """Replace the live node with a scripted fake, restoring it after."""
    fake = FakeRPC()
    monkeypatch.setattr(server.rpc, "json_rpc", fake.json_rpc)
    monkeypatch.setattr(server.rpc, "endpoint", fake.endpoint)
    return fake


@pytest.fixture
def call(client: Client) -> Callable[..., Any]:
    """Call a tool and hand back the text the model would read."""

    async def _call(name: str, **arguments: Any) -> str:
        result = await client.call_tool(name, arguments)
        assert not result.is_error, f"tool {name} failed: {result.content}"
        return result.content[0].text  # type: ignore[union-attr]

    return _call
