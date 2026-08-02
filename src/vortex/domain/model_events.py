"""模型流式调用产生的供应商无关事件。"""

from dataclasses import dataclass

from vortex.domain.tools import ToolCall


@dataclass(frozen=True, slots=True)
class TextDelta:
    """模型新生成的一段可见文本。"""

    text: str


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """一次完整模型调用的 Token 用量。"""

    input_tokens: int
    output_tokens: int
    total_tokens: int


@dataclass(frozen=True, slots=True)
class ModelCompleted:
    """模型调用已经正常结束。"""

    finish_reason: str
    usage: TokenUsage | None = None


@dataclass(frozen=True, slots=True)
class ToolCallAvailable:
    """Provider 已完整组装一个模型产生的工具调用。"""

    call: ToolCall


type ModelEvent = TextDelta | ToolCallAvailable | ModelCompleted
