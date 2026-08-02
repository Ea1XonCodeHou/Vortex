"""供应商无关的工具定义、调用与结果。"""

from dataclasses import dataclass
from enum import StrEnum


class ToolRisk(StrEnum):
    """工具对本地工作区可能产生的影响等级。"""

    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    NETWORK = "network"


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """提供给模型的工具名称、用途与 JSON Schema。"""

    name: str
    description: str
    input_schema: dict[str, object]
    risk: ToolRisk


@dataclass(frozen=True, slots=True)
class ToolCall:
    """模型生成的一次结构化工具调用。"""

    id: str
    name: str
    arguments: dict[str, object]


class ToolErrorCode(StrEnum):
    """可以稳定展示并回填给模型的工具错误类别。"""

    UNKNOWN_TOOL = "unknown_tool"
    INVALID_ARGUMENTS = "invalid_arguments"
    ACCESS_DENIED = "access_denied"
    PERMISSION_DENIED = "permission_denied"
    EXECUTION_LIMIT = "execution_limit"
    NOT_FOUND = "not_found"
    UNSUPPORTED_CONTENT = "unsupported_content"
    TIMEOUT = "timeout"
    EXECUTION_ERROR = "execution_error"


@dataclass(frozen=True, slots=True)
class ToolResult:
    """一次工具执行产生的 Observation。"""

    content: str
    is_error: bool = False
    error_code: ToolErrorCode | None = None

    def __post_init__(self) -> None:
        if self.is_error != (self.error_code is not None):
            raise ValueError("ToolResult errors require exactly one stable error code")

    @classmethod
    def success(cls, content: str) -> "ToolResult":
        """创建成功结果。"""
        return cls(content=content)

    @classmethod
    def failure(cls, content: str, code: ToolErrorCode) -> "ToolResult":
        """创建可回填给模型的失败结果。"""
        return cls(content=content, is_error=True, error_code=code)
