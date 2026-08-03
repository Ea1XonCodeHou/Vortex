"""所有本地和未来 MCP 工具共享的最小协议。"""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass

from vortex.domain.tools import ToolCall, ToolDefinition, ToolResult


@dataclass(frozen=True, slots=True)
class ToolPreparation:
    """已校验、可审批并可执行的一次工具调用。"""

    call: ToolCall
    approval_preview: str = ""
    payload: object | None = None
    execution_timeout_seconds: float | None = None


class BaseTool(ABC):
    """一个可注册、可描述并可异步调用的工具。"""

    definition: ToolDefinition

    async def prepare(self, call: ToolCall) -> ToolPreparation:
        """在不产生副作用的前提下准备工具调用。"""
        return ToolPreparation(call=call)

    @abstractmethod
    async def invoke(self, arguments: Mapping[str, object]) -> ToolResult:
        """校验并执行工具参数。"""
        ...

    async def invoke_prepared(self, preparation: ToolPreparation) -> ToolResult:
        """执行已准备调用；普通工具沿用原有 invoke 实现。"""
        return await self.invoke(preparation.call.arguments)
