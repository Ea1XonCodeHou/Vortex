"""无持久化的单 Agent 运行时与显式工具循环。"""

import asyncio
from collections.abc import AsyncIterator
from uuid import uuid4

from vortex.domain.changes import RevertResult, RevertStatus, TurnChangeSummary
from vortex.domain.messages import Message, MessageRole
from vortex.domain.model_events import ModelCompleted, TextDelta, TokenUsage, ToolCallAvailable
from vortex.domain.permissions import ApprovalDecision, ApprovalOutcome, ToolApprovalRequest
from vortex.domain.run_events import (
    AssistantTextDelta,
    RunFinished,
    RunStarted,
    RunStatus,
    RuntimeEvent,
    StepFinished,
    StepStarted,
    TerminationReason,
    ToolApprovalRequested,
    ToolApprovalResolved,
    ToolCallFinished,
    ToolCallStarted,
)
from vortex.domain.tools import ToolCall, ToolErrorCode, ToolResult, ToolRisk
from vortex.permissions.base import ApprovalManager
from vortex.providers.base import ModelProvider
from vortex.providers.errors import ModelError, ModelProtocolError
from vortex.runtime.budget import BudgetPolicy, RunBudgetScheduler
from vortex.tools.changes import TurnChangeTracker
from vortex.tools.executor import ToolExecutor
from vortex.tools.registry import ToolRegistry


class AgentBusyError(RuntimeError):
    """当前进程已有一个正在执行的 Agent Run。"""


class AgentRuntime:
    """维护临时历史并驱动 model → tool → observation 循环。"""

    def __init__(
        self,
        provider: ModelProvider,
        registry: ToolRegistry,
        approval_manager: ApprovalManager,
        *,
        system_prompt: str,
        max_iterations: int | None = None,
        max_tools_per_iteration: int = 8,
        max_stalled_iterations: int = 3,
        max_consecutive_tool_errors: int = 6,
        tool_timeout_seconds: float = 15.0,
        change_tracker: TurnChangeTracker | None = None,
    ) -> None:
        self._provider = provider
        self._registry = registry
        self._approval_manager = approval_manager
        self._executor = ToolExecutor(registry, timeout_seconds=tool_timeout_seconds)
        self._messages = [Message(MessageRole.SYSTEM, system_prompt)]
        self._budget_policy = BudgetPolicy(
            max_iterations=max_iterations,
            max_tools_per_iteration=max_tools_per_iteration,
            max_stalled_iterations=max_stalled_iterations,
            max_consecutive_tool_errors=max_consecutive_tool_errors,
        )
        self._run_lock = asyncio.Lock()
        self._change_lock = asyncio.Lock()
        self._change_tracker = change_tracker

    @property
    def model_name(self) -> str:
        """返回当前 Provider 使用的模型名称。"""
        return self._provider.model_name

    @property
    def messages(self) -> tuple[Message, ...]:
        """返回仅包含成功 Run 的当前进程历史。"""
        return tuple(self._messages)

    async def run(self, user_text: str) -> AsyncIterator[RuntimeEvent]:
        """执行进展感知的 Agent Run，并以类型化事件公开进度。"""
        goal = user_text.strip()
        if not goal:
            raise ValueError("User message cannot be empty")
        if self._run_lock.locked():
            raise AgentBusyError("An agent run is already active")

        async with self._run_lock:
            run_id = uuid4().hex
            working_messages = [*self._messages, Message(MessageRole.USER, goal)]
            total_usage: TokenUsage | None = None
            completed_iterations = 0
            executed_tool_calls = 0
            step_open = False
            safety_reason: TerminationReason | None = None
            scheduler = RunBudgetScheduler(self._budget_policy)

            if self._change_tracker is not None:
                async with self._change_lock:
                    self._change_tracker.begin_turn(run_id)
            yield RunStarted(run_id=run_id, goal=goal)

            try:
                iteration = 0
                while True:
                    iteration += 1
                    completed_iterations = iteration
                    step_open = True
                    yield StepStarted(run_id=run_id, iteration=iteration)

                    text_parts: list[str] = []
                    calls = []
                    completion: ModelCompleted | None = None

                    async for event in self._provider.stream(
                        working_messages,
                        self._registry.definitions(),
                    ):
                        if isinstance(event, TextDelta):
                            text_parts.append(event.text)
                            yield AssistantTextDelta(
                                run_id=run_id,
                                iteration=iteration,
                                text=event.text,
                            )
                        elif isinstance(event, ToolCallAvailable):
                            calls.append(event.call)
                        elif isinstance(event, ModelCompleted):
                            completion = event

                    if completion is None:
                        raise ModelProtocolError(
                            "The provider stream ended without a completion event",
                            user_message=(
                                "DeepSeek returned an incomplete response. Please try again."
                            ),
                            retryable=True,
                        )
                    total_usage = _merge_usage(total_usage, completion.usage)
                    response_text = "".join(text_parts)

                    if completion.finish_reason == "length":
                        raise ModelProtocolError(
                            "The model stopped because its output limit was reached",
                            user_message=(
                                "DeepSeek reached its output limit before finishing the task."
                            ),
                        )

                    assistant_message = Message(
                        MessageRole.ASSISTANT,
                        response_text,
                        tool_calls=tuple(calls),
                    )
                    working_messages.append(assistant_message)

                    if calls:
                        admitted_calls, deferred_calls = scheduler.admit_calls(calls)
                        observations: list[tuple[ToolCall, ToolResult]] = []
                        for call in admitted_calls:
                            yield ToolCallStarted(run_id=run_id, iteration=iteration, call=call)
                            prepared = await self._executor.prepare(call)
                            tool = self._registry.get(call.name)
                            if prepared.error is not None:
                                result = prepared.error
                                elapsed_ms = prepared.elapsed_ms
                            elif tool is not None:
                                assert prepared.preparation is not None
                                request = ToolApprovalRequest(
                                    run_id=run_id,
                                    iteration=iteration,
                                    call=call,
                                    risk=tool.definition.risk,
                                    allowed_decisions=_allowed_decisions(tool.definition.risk),
                                    preview=prepared.preparation.approval_preview,
                                )
                                yield ToolApprovalRequested(request)
                                outcome = await self._approval_manager.authorize(request)
                                if outcome.decision not in request.allowed_decisions:
                                    outcome = ApprovalOutcome(ApprovalDecision.DENY)
                                yield ToolApprovalResolved(request, outcome)
                                if outcome.decision is ApprovalDecision.DENY:
                                    result = ToolResult.failure(
                                        f"Permission denied for tool: {call.name}.",
                                        ToolErrorCode.PERMISSION_DENIED,
                                    )
                                    elapsed_ms = 0
                                else:
                                    execution = await self._executor.execute_prepared(
                                        prepared.preparation
                                    )
                                    executed_tool_calls += 1
                                    result = execution.result
                                    elapsed_ms = execution.elapsed_ms
                            else:
                                raise RuntimeError("Prepared tool disappeared from the registry")
                            yield ToolCallFinished(
                                run_id=run_id,
                                iteration=iteration,
                                call=call,
                                result=result,
                                elapsed_ms=elapsed_ms,
                            )
                            working_messages.append(
                                Message(
                                    MessageRole.TOOL,
                                    _observation_content(result),
                                    tool_call_id=call.id,
                                )
                            )
                            observations.append((call, result))

                        for call in deferred_calls:
                            yield ToolCallStarted(run_id=run_id, iteration=iteration, call=call)
                            result = ToolResult.failure(
                                "This model step requested too many tools. Request this call "
                                "again in a later step if it is still needed.",
                                ToolErrorCode.EXECUTION_LIMIT,
                            )
                            yield ToolCallFinished(
                                run_id=run_id,
                                iteration=iteration,
                                call=call,
                                result=result,
                                elapsed_ms=0,
                            )
                            working_messages.append(
                                Message(
                                    MessageRole.TOOL,
                                    _observation_content(result),
                                    tool_call_id=call.id,
                                )
                            )

                        yield StepFinished(run_id=run_id, iteration=iteration)
                        step_open = False
                        safety_reason = scheduler.observe_iteration(observations)
                        if safety_reason is None:
                            safety_reason = scheduler.iteration_limit_reason(iteration)
                        if safety_reason is not None:
                            break
                        continue

                    if not response_text.strip():
                        raise ModelProtocolError(
                            "The model returned neither text nor tool calls",
                            user_message="DeepSeek returned an empty response. Please try again.",
                            retryable=True,
                        )

                    yield StepFinished(run_id=run_id, iteration=iteration)
                    step_open = False
                    self._messages = working_messages
                    yield RunFinished(
                        run_id=run_id,
                        status=RunStatus.SUCCEEDED,
                        reason=TerminationReason.COMPLETED,
                        iterations=iteration,
                        tool_calls=executed_tool_calls,
                        final_output=response_text,
                        usage=total_usage,
                        changes=self._finish_changes(run_id),
                    )
                    return

                if safety_reason is None:
                    raise RuntimeError("Agent loop ended without a completion or safety reason")

                final_iteration = completed_iterations + 1
                completed_iterations = final_iteration
                step_open = True
                yield StepStarted(run_id=run_id, iteration=final_iteration)
                finalization_messages = [
                    *working_messages,
                    Message(MessageRole.SYSTEM, _safety_finalization_prompt(safety_reason)),
                ]
                text_parts = []
                calls = []
                completion = None
                async for event in self._provider.stream(finalization_messages, ()):
                    if isinstance(event, TextDelta):
                        text_parts.append(event.text)
                    elif isinstance(event, ToolCallAvailable):
                        calls.append(event.call)
                    elif isinstance(event, ModelCompleted):
                        completion = event

                if completion is None:
                    raise ModelProtocolError(
                        "The provider finalization stream ended without a completion event",
                        user_message="DeepSeek returned an incomplete response. Please try again.",
                        retryable=True,
                    )
                total_usage = _merge_usage(total_usage, completion.usage)
                response_text = "".join(text_parts)
                if completion.finish_reason == "length":
                    raise ModelProtocolError(
                        "The model stopped during budget finalization because its output limit "
                        "was reached",
                        user_message=(
                            "DeepSeek reached its output limit before finishing the task."
                        ),
                    )
                valid_finalization = (
                    not calls
                    and bool(response_text.strip())
                    and not _contains_tool_protocol_artifact(response_text)
                )
                if valid_finalization:
                    yield AssistantTextDelta(
                        run_id=run_id,
                        iteration=final_iteration,
                        text=response_text,
                    )
                yield StepFinished(run_id=run_id, iteration=final_iteration)
                step_open = False

                if not valid_finalization:
                    yield RunFinished(
                        run_id=run_id,
                        status=RunStatus.LIMIT_REACHED,
                        reason=safety_reason,
                        iterations=final_iteration,
                        tool_calls=executed_tool_calls,
                        usage=total_usage,
                        changes=self._finish_changes(run_id),
                    )
                    return

                working_messages.append(Message(MessageRole.ASSISTANT, response_text))
                self._messages = working_messages
                yield RunFinished(
                    run_id=run_id,
                    status=RunStatus.SUCCEEDED,
                    reason=TerminationReason.SAFETY_FINALIZED,
                    iterations=final_iteration,
                    tool_calls=executed_tool_calls,
                    final_output=response_text,
                    usage=total_usage,
                    changes=self._finish_changes(run_id),
                )
                return
            except asyncio.CancelledError:
                if step_open:
                    yield StepFinished(run_id=run_id, iteration=completed_iterations)
                yield RunFinished(
                    run_id=run_id,
                    status=RunStatus.CANCELLED,
                    reason=TerminationReason.CANCELLED,
                    iterations=completed_iterations,
                    tool_calls=executed_tool_calls,
                    usage=total_usage,
                    changes=self._finish_changes(run_id),
                )
                raise
            except ModelProtocolError:
                if step_open:
                    yield StepFinished(run_id=run_id, iteration=completed_iterations)
                yield RunFinished(
                    run_id=run_id,
                    status=RunStatus.FAILED,
                    reason=TerminationReason.PROTOCOL_ERROR,
                    iterations=completed_iterations,
                    tool_calls=executed_tool_calls,
                    usage=total_usage,
                    changes=self._finish_changes(run_id),
                )
                raise
            except ModelError:
                if step_open:
                    yield StepFinished(run_id=run_id, iteration=completed_iterations)
                yield RunFinished(
                    run_id=run_id,
                    status=RunStatus.FAILED,
                    reason=TerminationReason.MODEL_ERROR,
                    iterations=completed_iterations,
                    tool_calls=executed_tool_calls,
                    usage=total_usage,
                    changes=self._finish_changes(run_id),
                )
                raise
            except Exception:
                if step_open:
                    yield StepFinished(run_id=run_id, iteration=completed_iterations)
                yield RunFinished(
                    run_id=run_id,
                    status=RunStatus.FAILED,
                    reason=TerminationReason.RUNTIME_ERROR,
                    iterations=completed_iterations,
                    tool_calls=executed_tool_calls,
                    usage=total_usage,
                    changes=self._finish_changes(run_id),
                )
                raise

    async def revert_latest_turn(self, run_id: str) -> RevertResult:
        """撤销最新完成 Run 的全部 Vortex 文件修改。"""
        if self._run_lock.locked():
            return RevertResult(
                RevertStatus.UNAVAILABLE,
                message="Wait for the active task to finish before reverting changes.",
            )
        if self._change_tracker is None:
            return RevertResult(
                RevertStatus.UNAVAILABLE,
                message="No workspace changes are available to revert.",
            )
        async with self._change_lock:
            result = await self._change_tracker.revert_latest(run_id)
        if result.status is RevertStatus.REVERTED:
            self._messages.append(
                Message(
                    MessageRole.SYSTEM,
                    "The user reverted all workspace file changes made by the previous task. "
                    "Treat those edits as no longer present.",
                )
            )
        return result

    def _finish_changes(self, run_id: str) -> TurnChangeSummary | None:
        """冻结一个 Run 的净文件变化。"""
        if self._change_tracker is None:
            return None
        return self._change_tracker.finish_turn(run_id)

    async def aclose(self) -> None:
        """关闭 Provider 持有的网络资源。"""
        await self._provider.aclose()


def _merge_usage(current: TokenUsage | None, incoming: TokenUsage | None) -> TokenUsage | None:
    """累计同一个 Run 中多次模型调用的 Token 用量。"""
    if incoming is None:
        return current
    if current is None:
        return incoming
    return TokenUsage(
        input_tokens=current.input_tokens + incoming.input_tokens,
        output_tokens=current.output_tokens + incoming.output_tokens,
        total_tokens=current.total_tokens + incoming.total_tokens,
    )


def _observation_content(result: ToolResult) -> str:
    """保留工具错误类别，使模型能区分失败 Observation。"""
    if not result.is_error:
        return result.content
    assert result.error_code is not None
    return f"Tool error [{result.error_code.value}]: {result.content}"


def _allowed_decisions(risk: ToolRisk) -> tuple[ApprovalDecision, ...]:
    """写操作按 Run 授权；只读操作可按次或按会话授权。"""
    if risk is ToolRisk.WRITE:
        return (ApprovalDecision.ALLOW_TURN, ApprovalDecision.DENY)
    if risk in {ToolRisk.EXECUTE, ToolRisk.NETWORK}:
        return (ApprovalDecision.ALLOW_ONCE, ApprovalDecision.DENY)
    return (
        ApprovalDecision.ALLOW_ONCE,
        ApprovalDecision.ALLOW_SESSION,
        ApprovalDecision.DENY,
    )


def _safety_finalization_prompt(reason: TerminationReason) -> str:
    """要求模型在安全停止后基于已有证据完成交付。"""
    explanation = (
        "recent tool calls stopped producing new observations or repeatedly failed"
        if reason is TerminationReason.STALLED
        else "the explicitly configured automation step limit was reached"
    )
    return (
        f"Agent execution paused because {explanation} ({reason.value}). "
        "No more tools are available. Produce the best possible final answer using only the "
        "evidence already collected. Clearly state any material uncertainty, but do not ask to "
        "call another tool."
    )


def _contains_tool_protocol_artifact(text: str) -> bool:
    """拒绝把供应商内部工具协议降级成最终可见文本。"""
    normalized = text.lower()
    return "<|dsml|" in normalized or "<|tool_calls" in normalized
