"""Agent Runtime 对客户端公开的类型化运行事件。"""

from dataclasses import dataclass
from enum import StrEnum

from vortex.domain.model_events import TokenUsage
from vortex.domain.permissions import ApprovalOutcome, ToolApprovalRequest
from vortex.domain.tools import ToolCall, ToolResult


class RunStatus(StrEnum):
    """一次 Agent Run 的正式状态。"""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    LIMIT_REACHED = "limit_reached"


class TerminationReason(StrEnum):
    """Run 结束的稳定原因。"""

    COMPLETED = "completed"
    MODEL_ERROR = "model_error"
    PROTOCOL_ERROR = "protocol_error"
    RUNTIME_ERROR = "runtime_error"
    CANCELLED = "cancelled"
    MAX_ITERATIONS = "max_iterations"
    MAX_TOOL_CALLS = "max_tool_calls"
    BUDGET_FINALIZED = "budget_finalized"


@dataclass(frozen=True, slots=True)
class RunStarted:
    """Runtime 已接受一项用户任务。"""

    run_id: str
    goal: str


@dataclass(frozen=True, slots=True)
class StepStarted:
    """一次新的模型决策迭代已经开始。"""

    run_id: str
    iteration: int


@dataclass(frozen=True, slots=True)
class AssistantTextDelta:
    """模型在当前迭代中新生成的可见文本。"""

    run_id: str
    iteration: int
    text: str


@dataclass(frozen=True, slots=True)
class ToolCallStarted:
    """Runtime 即将执行模型请求的工具。"""

    run_id: str
    iteration: int
    call: ToolCall


@dataclass(frozen=True, slots=True)
class ToolApprovalRequested:
    """工具调用正在等待用户或会话策略审批。"""

    request: ToolApprovalRequest


@dataclass(frozen=True, slots=True)
class ToolApprovalResolved:
    """工具审批已经得到明确结果。"""

    request: ToolApprovalRequest
    outcome: ApprovalOutcome


@dataclass(frozen=True, slots=True)
class ToolCallFinished:
    """工具执行完成并产生了 Observation。"""

    run_id: str
    iteration: int
    call: ToolCall
    result: ToolResult
    elapsed_ms: int


@dataclass(frozen=True, slots=True)
class StepFinished:
    """当前模型决策及其工具调用已经处理完毕。"""

    run_id: str
    iteration: int


@dataclass(frozen=True, slots=True)
class RunFinished:
    """Run 已以明确状态终止。"""

    run_id: str
    status: RunStatus
    reason: TerminationReason
    iterations: int
    tool_calls: int
    final_output: str = ""
    usage: TokenUsage | None = None


type RuntimeEvent = (
    RunStarted
    | StepStarted
    | AssistantTextDelta
    | ToolCallStarted
    | ToolApprovalRequested
    | ToolApprovalResolved
    | ToolCallFinished
    | StepFinished
    | RunFinished
)
