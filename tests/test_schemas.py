"""What the server advertises in `tools/list`.

The schema is the contract a client validates against, so the parts that
protect the caller -- bounds on numeric arguments -- are asserted here.

Every tool is text-only and returns `str`, so every tool must pass
`structured_output=False`.
"""

from __future__ import annotations

import anyio
import pytest
from mcp import Client

import server

TOOLS = {
    "get_info",
    "get_block_count",
    "get_last_block_header",
    "get_block_header_by_height",
    "get_block_header_by_hash",
    "get_block",
    "get_version",
    "get_fee_estimate",
    "get_transactions",
    "get_transaction_pool_stats",
}


@pytest.fixture
def advertised() -> dict:
    """The tools/list result, fetched once per test through a real client."""

    async def _list():
        async with Client(server.mcp) as c:
            return await c.list_tools()

    listing = anyio.run(_list)
    return {tool.name: tool for tool in listing.tools}


def test_every_tool_is_advertised(advertised: dict) -> None:
    assert set(advertised) == TOOLS


@pytest.mark.parametrize("name", sorted(TOOLS))
def test_text_tools_publish_no_output_schema(advertised: dict, name: str) -> None:
    assert advertised[name].output_schema is None, (
        f"{name} publishes an output schema; pass structured_output=False"
    )


@pytest.mark.parametrize(
    "name,field,minimum",
    [
        ("get_block_header_by_height", "height", 0),
        ("get_fee_estimate", "grace_blocks", 0),
    ],
)
def test_numeric_arguments_are_bounded(
    advertised: dict, name: str, field: str, minimum: int
) -> None:
    schema = advertised[name].input_schema["properties"][field]
    assert schema.get("minimum") == minimum, f"{name}.{field} has no lower bound"


def test_get_block_height_is_nullable_and_bounded(advertised: dict) -> None:
    schema = advertised["get_block"].input_schema["properties"]["height"]
    (int_arm,) = (arm for arm in schema["anyOf"] if arm.get("type") == "integer")
    assert int_arm.get("minimum") == 0


def test_every_tool_declares_itself_read_only(advertised: dict) -> None:
    for name, tool in advertised.items():
        assert tool.annotations is not None, f"{name} publishes no annotations"
        assert tool.annotations.read_only_hint is True, f"{name} is not marked read-only"
        assert tool.annotations.open_world_hint is True, f"{name} is not marked open-world"
