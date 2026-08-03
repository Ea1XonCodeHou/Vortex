"""Agent Run 的进展感知安全调度。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from vortex.domain.run_events import TerminationReason
from vortex.domain.tools import ToolErrorCode

if TYPE_CHECKING:
    from collections.abc import Sequence

    from vortex.domain.tools import ToolCall, ToolResult


@dataclass(frozen=True, slots=True)
class BudgetPolicy:
    """限制单轮负载，并只在 Run 失去进展时触发安全停止。"""

    max_iterations: int | None = None
    max_tools_per_iteration: int = 8
    max_stalled_iterations: int = 3
    max_consecutive_tool_errors: int = 6

    def __post_init__(self) -> None:
        if self.max_iterations is not None and self.max_iterations <= 0:
            raise ValueError("max_iterations must be positive when configured")
        if self.max_tools_per_iteration <= 0:
            raise ValueError("max_tools_per_iteration must be positive")
        if self.max_stalled_iterations <= 0:
            raise ValueError("max_stalled_iterations must be positive")
        if self.max_consecutive_tool_errors <= 0:
            raise ValueError("max_consecutive_tool_errors must be positive")


@dataclass(slots=True)
class RunBudgetScheduler:
    """以新 Observation 作为进展信号，而不是消耗固定总调用额度。"""

    policy: BudgetPolicy
    _seen_observations: set[str] = field(default_factory=set, init=False)
    _stalled_iterations: int = field(default=0, init=False)
    _consecutive_tool_errors: int = field(default=0, init=False)

    def admit_calls(
        self,
        calls: Sequence[ToolCall],
    ) -> tuple[tuple[ToolCall, ...], tuple[ToolCall, ...]]:
        """限制单次模型决策的调用规模，但不消耗 Run 级总额度。"""
        limit = self.policy.max_tools_per_iteration
        return tuple(calls[:limit]), tuple(calls[limit:])

    def observe_iteration(
        self,
        observations: Sequence[tuple[ToolCall, ToolResult]],
    ) -> TerminationReason | None:
        """记录一轮真实 Observation，并在重复或连续失败时报告停滞。"""
        made_progress = False
        for call, result in observations:
            fingerprint = _observation_fingerprint(call, result)
            if fingerprint not in self._seen_observations:
                self._seen_observations.add(fingerprint)
                made_progress = True

            if result.error_code in _CONTROL_FAILURE_CODES:
                self._consecutive_tool_errors += 1
            else:
                self._consecutive_tool_errors = 0

        if made_progress:
            self._stalled_iterations = 0
        else:
            self._stalled_iterations += 1

        if self._consecutive_tool_errors >= self.policy.max_consecutive_tool_errors:
            return TerminationReason.STALLED
        if self._stalled_iterations >= self.policy.max_stalled_iterations:
            return TerminationReason.STALLED
        return None

    def iteration_limit_reason(self, iteration: int) -> TerminationReason | None:
        """仅在调用方显式配置无人值守上限时终止。"""
        limit = self.policy.max_iterations
        if limit is not None and iteration >= limit:
            return TerminationReason.MAX_ITERATIONS
        return None


def _observation_fingerprint(call: ToolCall, result: ToolResult) -> str:
    """忽略供应商 call id，稳定识别相同调用得到的相同结果。"""
    payload = {
        "tool": call.name,
        "arguments": call.arguments,
        "content": result.content,
        "error_code": result.error_code.value if result.error_code is not None else None,
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


# 这些错误没有产生任务层面的新证据；命令非零退出、未找到目标等结果仍可推动诊断。
_CONTROL_FAILURE_CODES = frozenset(
    {
        ToolErrorCode.UNKNOWN_TOOL,
        ToolErrorCode.INVALID_ARGUMENTS,
        ToolErrorCode.ACCESS_DENIED,
        ToolErrorCode.PERMISSION_DENIED,
        ToolErrorCode.TIMEOUT,
        ToolErrorCode.EXECUTION_ERROR,
    }
)
