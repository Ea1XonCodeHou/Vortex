"""工具注册与统一调用管道测试。"""

import asyncio
from collections.abc import Mapping

import pytest

from tests.support.fake_tool import FakeTool
from vortex.domain.tools import ToolCall, ToolDefinition, ToolErrorCode, ToolResult, ToolRisk
from vortex.tools.base import BaseTool
from vortex.tools.executor import ToolExecutor
from vortex.tools.registry import ToolRegistry


class _SlowTool(BaseTool):
    definition = ToolDefinition(
        name="slow",
        description="Wait forever.",
        input_schema={"type": "object", "properties": {}},
        risk=ToolRisk.READ,
    )

    async def invoke(self, arguments: Mapping[str, object]) -> ToolResult:
        del arguments
        await asyncio.Event().wait()
        return ToolResult.success("unreachable")


def test_registry_preserves_order_and_rejects_duplicate_names() -> None:
    first = FakeTool(ToolResult.success("ok"))
    registry = ToolRegistry((first,))

    assert registry.get("inspect") is first
    assert [definition.name for definition in registry.definitions()] == ["inspect"]

    with pytest.raises(ValueError, match="Tool is already registered: inspect"):
        registry.register(FakeTool(ToolResult.success("duplicate")))


async def test_executor_returns_unknown_tool_and_timeout_as_observations() -> None:
    executor = ToolExecutor(ToolRegistry((_SlowTool(),)), timeout_seconds=0.01)

    missing = await executor.execute(ToolCall(id="1", name="missing", arguments={}))
    timed_out = await executor.execute(ToolCall(id="2", name="slow", arguments={}))

    assert missing.result.error_code is ToolErrorCode.UNKNOWN_TOOL
    assert timed_out.result.error_code is ToolErrorCode.TIMEOUT


def test_tool_result_rejects_inconsistent_error_state() -> None:
    with pytest.raises(ValueError, match="stable error code"):
        ToolResult("failed", is_error=True)

    with pytest.raises(ValueError, match="stable error code"):
        ToolResult("ok", error_code=ToolErrorCode.EXECUTION_ERROR)
