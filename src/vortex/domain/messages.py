"""与模型供应商无关的消息定义。"""

from dataclasses import dataclass
from enum import StrEnum

from vortex.domain.tools import ToolCall


class MessageRole(StrEnum):
    """当前对话阶段支持的消息角色。"""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass(frozen=True, slots=True)
class Message:
    """一次对话中的不可变消息，支持原生工具调用与结果回填。"""

    role: MessageRole
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None

    def __post_init__(self) -> None:
        if self.tool_calls and self.role is not MessageRole.ASSISTANT:
            raise ValueError("Only assistant messages may contain tool calls")
        if self.role is MessageRole.TOOL and not self.tool_call_id:
            raise ValueError("Tool messages require a tool_call_id")
        if self.role is not MessageRole.TOOL and self.tool_call_id is not None:
            raise ValueError("Only tool messages may contain a tool_call_id")
