"""无持久化的单 Agent 运行时与显式工具循环。"""

import asyncio
from collections.abc import AsyncIterator
from uuid import uuid4

from vortex.domain.messages import Message, MessageRole
from vortex.domain.model_events import ModelCompleted, TextDelta, TokenUsage, ToolCallAvailable
from vortex.domain.permissions import ApprovalDecision, ToolApprovalRequest
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
from vortex.domain.tools import ToolErrorCode, ToolResult
from vortex.permissions.base import ApprovalManager
from vortex.providers.base import ModelProvider
from vortex.providers.errors import ModelError, ModelProtocolError
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
        max_iterations: int = 24,
        max_tool_calls: int = 64,
        tool_timeout_seconds: float = 15.0,
    ) -> None:
        if max_iterations <= 0:
            raise ValueError("max_iterations must be positive")
        if max_tool_calls <= 0:
            raise ValueError("max_tool_calls must be positive")
        self._provider = provider
        self._registry = registry
        self._approval_manager = approval_manager
        self._executor = ToolExecutor(registry, timeout_seconds=tool_timeout_seconds)
        self._messages = [Message(MessageRole.SYSTEM, system_prompt)]
        self._max_iterations = max_iterations
        self._max_tool_calls = max_tool_calls
        self._run_lock = asyncio.Lock()

    @property
    def model_name(self) -> str:
        """返回当前 Provider 使用的模型名称。"""
        return self._provider.model_name

    @property
    def messages(self) -> tuple[Message, ...]:
        """返回仅包含成功 Run 的当前进程历史。"""
        return tuple(self._messages)

    async def run(self, user_text: str) -> AsyncIterator[RuntimeEvent]:
        """执行一个有界 Agent Run，并以类型化事件公开进度。"""
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
            budget_reason: TerminationReason | None = None

            yield RunStarted(run_id=run_id, goal=goal)

            try:
                for iteration in range(1, self._max_iterations + 1):
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
                        if executed_tool_calls + len(calls) > self._max_tool_calls:
                            for call in calls:
                                yield ToolCallStarted(
                                    run_id=run_id,
                                    iteration=iteration,
                                    call=call,
                                )
                                result = ToolResult.failure(
                                    "The configured tool-call budget is exhausted.",
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
                            budget_reason = TerminationReason.MAX_TOOL_CALLS
                            break

                        for call in calls:
                            yield ToolCallStarted(run_id=run_id, iteration=iteration, call=call)
                            tool = self._registry.get(call.name)
                            if tool is not None:
                                request = ToolApprovalRequest(
                                    run_id=run_id,
                                    iteration=iteration,
                                    call=call,
                                    risk=tool.definition.risk,
                                )
                                yield ToolApprovalRequested(request)
                                outcome = await self._approval_manager.authorize(request)
                                yield ToolApprovalResolved(request, outcome)
                            else:
                                outcome = None

                            if outcome is not None and outcome.decision is ApprovalDecision.DENY:
                                result = ToolResult.failure(
                                    f"Permission denied for tool: {call.name}.",
                                    ToolErrorCode.PERMISSION_DENIED,
                                )
                                elapsed_ms = 0
                            else:
                                execution = await self._executor.execute(call)
                                executed_tool_calls += 1
                                result = execution.result
                                elapsed_ms = execution.elapsed_ms
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

                        yield StepFinished(run_id=run_id, iteration=iteration)
                        step_open = False
                        if iteration == self._max_iterations:
                            budget_reason = TerminationReason.MAX_ITERATIONS
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
                    )
                    return

                if budget_reason is None:
                    raise RuntimeError("Agent loop ended without a completion or budget reason")

                final_iteration = completed_iterations + 1
                completed_iterations = final_iteration
                step_open = True
                yield StepStarted(run_id=run_id, iteration=final_iteration)
                finalization_messages = [
                    *working_messages,
                    Message(MessageRole.SYSTEM, _budget_finalization_prompt(budget_reason)),
                ]
                text_parts = []
                calls = []
                completion = None
                async for event in self._provider.stream(finalization_messages, ()):
                    if isinstance(event, TextDelta):
                        text_parts.append(event.text)
                        yield AssistantTextDelta(
                            run_id=run_id,
                            iteration=final_iteration,
                            text=event.text,
                        )
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
                yield StepFinished(run_id=run_id, iteration=final_iteration)
                step_open = False

                if calls or not response_text.strip():
                    yield RunFinished(
                        run_id=run_id,
                        status=RunStatus.LIMIT_REACHED,
                        reason=budget_reason,
                        iterations=final_iteration,
                        tool_calls=executed_tool_calls,
                        usage=total_usage,
                    )
                    return

                working_messages.append(Message(MessageRole.ASSISTANT, response_text))
                self._messages = working_messages
                yield RunFinished(
                    run_id=run_id,
                    status=RunStatus.SUCCEEDED,
                    reason=TerminationReason.BUDGET_FINALIZED,
                    iterations=final_iteration,
                    tool_calls=executed_tool_calls,
                    final_output=response_text,
                    usage=total_usage,
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
                )
                raise

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


def _budget_finalization_prompt(reason: TerminationReason) -> str:
    """要求模型在探索预算耗尽后基于现有证据完成交付。"""
    return (
        f"The workspace exploration budget is exhausted ({reason.value}). "
        "No more tools are available. Produce the best possible final answer using only the "
        "evidence already collected. Clearly state any material uncertainty, but do not ask to "
        "call another tool."
    )
