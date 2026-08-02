"""所有本地和未来 MCP 工具共享的最小协议。"""

from abc import ABC, abstractmethod
from collections.abc import Mapping

from vortex.domain.tools import ToolDefinition, ToolResult


class BaseTool(ABC):
    """一个可注册、可描述并可异步调用的工具。"""

    definition: ToolDefinition

    @abstractmethod
    async def invoke(self, arguments: Mapping[str, object]) -> ToolResult:
        """校验并执行工具参数。"""
        ...
