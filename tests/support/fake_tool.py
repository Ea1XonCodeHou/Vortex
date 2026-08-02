"""Agent Runtime 测试使用的确定性工具。"""

from collections.abc import Mapping

from vortex.domain.tools import ToolDefinition, ToolResult, ToolRisk
from vortex.tools.base import BaseTool


class FakeTool(BaseTool):
    """记录参数并返回预设 Observation。"""

    definition = ToolDefinition(
        name="inspect",
        description="Inspect a test value.",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
        risk=ToolRisk.READ,
    )

    def __init__(self, result: ToolResult) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    async def invoke(self, arguments: Mapping[str, object]) -> ToolResult:
        self.calls.append(dict(arguments))
        return self.result
