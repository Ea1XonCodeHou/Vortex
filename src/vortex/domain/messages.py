"""与模型供应商无关的消息定义。"""

from dataclasses import dataclass
from enum import StrEnum


class MessageRole(StrEnum):
    """当前对话阶段支持的消息角色。"""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True, slots=True)
class Message:
    """一次对话中的不可变消息。"""

    role: MessageRole
    content: str
