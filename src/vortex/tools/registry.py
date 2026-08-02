"""进程内工具注册与发现。"""

from collections.abc import Iterable

from vortex.domain.tools import ToolDefinition
from vortex.tools.base import BaseTool


class ToolRegistry:
    """维护工具实现，并向模型提供确定顺序的定义列表。"""

    def __init__(self, tools: Iterable[BaseTool] = ()) -> None:
        self._tools: dict[str, BaseTool] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: BaseTool) -> None:
        """注册一个工具，拒绝容易隐藏配置错误的同名覆盖。"""
        name = tool.definition.name
        if name in self._tools:
            raise ValueError(f"Tool is already registered: {name}")
        self._tools[name] = tool

    def get(self, name: str) -> BaseTool | None:
        """按模型提供的名称查找工具实现。"""
        return self._tools.get(name)

    def definitions(self) -> tuple[ToolDefinition, ...]:
        """返回当前允许暴露给模型的工具定义。"""
        return tuple(tool.definition for tool in self._tools.values())
