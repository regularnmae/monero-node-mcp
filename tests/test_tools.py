"""Tool behaviour, driven through the in-memory client against a fake node.

The fake records the call each tool made, so these tests pin the parameter
shaping (a height or a hash, never both) and which transport each tool uses
-- `/json_rpc` for the methods, the root endpoints for transactions and pool
stats.
"""

from __future__ import annotations

import json

import pytest

from rpc import RPCError

HASH = "cd" * 32


@pytest.mark.anyio
async def test_get_info_is_rendered_as_json(call, fake_rpc) -> None:
    fake_rpc.json_rpc_answers["get_info"] = {"height": 3784449, "status": "OK"}
    text = await call("get_info")
    assert json.loads(text)["height"] == 3784449
    assert fake_rpc.calls == [("json_rpc", "get_info", None)]


@pytest.mark.anyio
async def test_get_block_requires_exactly_one_selector(call, fake_rpc) -> None:
    assert "exactly one" in await call("get_block")
    assert "exactly one" in await call("get_block", height=5, block_hash=HASH)
    # A malformed call must not reach the node.
    assert fake_rpc.calls == []


@pytest.mark.anyio
async def test_get_block_by_height_forwards_height_and_trims_blob(call, fake_rpc) -> None:
    fake_rpc.json_rpc_answers["get_block"] = {
        "block_header": {"height": 7},
        "blob": "deadbeef" * 1000,
        "json": "{}",
        "tx_hashes": [],
    }
    text = await call("get_block", height=7)
    assert fake_rpc.calls == [("json_rpc", "get_block", {"height": 7})]
    payload = json.loads(text)
    assert payload["block_header"]["height"] == 7
    assert "blob" not in payload, "the raw block blob should be trimmed"


@pytest.mark.anyio
async def test_get_block_by_hash_forwards_hash(call, fake_rpc) -> None:
    fake_rpc.json_rpc_answers["get_block"] = {"block_header": {"height": 1}}
    await call("get_block", block_hash=HASH)
    assert fake_rpc.calls == [("json_rpc", "get_block", {"hash": HASH})]


@pytest.mark.anyio
async def test_get_transactions_uses_the_rest_endpoint(call, fake_rpc) -> None:
    fake_rpc.endpoint_answers["/get_transactions"] = {"status": "OK", "missed_tx": []}
    await call("get_transactions", txids=[HASH])
    assert fake_rpc.calls == [
        ("endpoint", "/get_transactions", {"txs_hashes": [HASH], "decode_as_json": False})
    ]


@pytest.mark.anyio
async def test_pool_stats_uses_the_rest_endpoint(call, fake_rpc) -> None:
    fake_rpc.endpoint_answers["/get_transaction_pool_stats"] = {"status": "OK"}
    await call("get_transaction_pool_stats")
    assert fake_rpc.calls == [("endpoint", "/get_transaction_pool_stats", None)]


@pytest.mark.anyio
async def test_unknown_rpc_error_is_surfaced_with_its_code(call, fake_rpc) -> None:
    fake_rpc.json_rpc_answers["get_version"] = RPCError("method not found", -32601)
    text = await call("get_version")
    assert "method not found" in text
    assert "-32601" in text


@pytest.mark.anyio
async def test_transport_error_has_no_code(call, fake_rpc) -> None:
    fake_rpc.json_rpc_answers["get_info"] = RPCError("cannot reach the node at http://monerod:18089")
    text = await call("get_info")
    assert "cannot reach the node" in text
