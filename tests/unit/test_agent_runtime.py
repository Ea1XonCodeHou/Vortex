"""纯内存单 Agent Loop 的确定性测试。"""

import asyncio

import pytest

from tests.support.fake_approval import FakeApprovalManager
from tests.support.fake_provider import BlockingProvider, FakeProvider
from tests.support.fake_tool import FakeTool
from vortex.domain.messages import Message, MessageRole
from vortex.domain.model_events import ModelCompleted, TokenUsage, ToolCallAvailable
from vortex.domain.permissions import ApprovalDecision, ApprovalOutcome, ToolApprovalRequest
from vortex.domain.run_events import (
    AssistantTextDelta,
    RunFinished,
    RunStarted,
    RunStatus,
    StepFinished,
    StepStarted,
    TerminationReason,
    ToolApprovalRequested,
    ToolApprovalResolved,
    ToolCallFinished,
    ToolCallStarted,
)
from vortex.domain.tools import ToolCall, ToolErrorCode, ToolResult
from vortex.providers.errors import ModelError
from vortex.runtime.agent import AgentRuntime
from vortex.tools.registry import ToolRegistry


def _call(identifier: str = "call-1") -> ToolCall:
    return ToolCall(id=identifier, name="inspect", arguments={"path": "README.md"})


class _FailingApprovalManager:
    async def authorize(self, request: ToolApprovalRequest) -> ApprovalOutcome:
        del request
        raise RuntimeError("approval callback failed")


def _runtime(
    provider: FakeProvider | BlockingProvider,
    tool: FakeTool | None = None,
    *,
    max_iterations: int = 10,
    max_tool_calls: int = 20,
) -> AgentRuntime:
    registry = ToolRegistry((tool,)) if tool is not None else ToolRegistry()
    return AgentRuntime(
        provider,
        registry,
        FakeApprovalManager(),
        system_prompt="You are Vortex.",
        max_iterations=max_iterations,
        max_tool_calls=max_tool_calls,
    )


async def test_tool_observation_drives_second_model_turn_and_commits_atomically() -> None:
    call = _call()
    provider = FakeProvider(
        [
            [ToolCallAvailable(call), ModelCompleted(finish_reason="tool_calls")],
            [
                "Workspace summary",
                ModelCompleted(
                    finish_reason="stop",
                    usage=TokenUsage(input_tokens=20, output_tokens=4, total_tokens=24),
                ),
            ],
        ]
    )
    tool = FakeTool(ToolResult.success("README contents"))
    runtime = _runtime(provider, tool)

    events = [event async for event in runtime.run("Inspect this workspace")]

    assert [type(event) for event in events] == [
        RunStarted,
        StepStarted,
        ToolCallStarted,
        ToolApprovalRequested,
        ToolApprovalResolved,
        ToolCallFinished,
        StepFinished,
        StepStarted,
        AssistantTextDelta,
        StepFinished,
        RunFinished,
    ]
    assert tool.calls == [{"path": "README.md"}]
    assert provider.requests[1][-1] == Message(
        MessageRole.TOOL,
        "README contents",
        tool_call_id="call-1",
    )
    assert [message.role for message in runtime.messages] == [
        MessageRole.SYSTEM,
        MessageRole.USER,
        MessageRole.ASSISTANT,
        MessageRole.TOOL,
        MessageRole.ASSISTANT,
    ]
    finished = events[-1]
    assert isinstance(finished, RunFinished)
    assert finished.status is RunStatus.SUCCEEDED
    assert finished.iterations == 2
    assert finished.tool_calls == 1
    assert finished.final_output == "Workspace summary"


async def test_recoverable_tool_error_is_returned_to_model_and_loop_continues() -> None:
    call = _call()
    provider = FakeProvider(
        [
            [ToolCallAvailable(call), ModelCompleted(finish_reason="tool_calls")],
            ["Recovered", ModelCompleted(finish_reason="stop")],
        ]
    )
    tool = FakeTool(ToolResult.failure("Path does not exist: missing.py", ToolErrorCode.NOT_FOUND))
    runtime = _runtime(provider, tool)

    events = [event async for event in runtime.run("Inspect a missing file")]

    tool_finished = next(event for event in events if isinstance(event, ToolCallFinished))
    assert tool_finished.result.is_error is True
    assert provider.requests[1][-1].content == (
        "Tool error [not_found]: Path does not exist: missing.py"
    )
    assert isinstance(events[-1], RunFinished)
    assert events[-1].status is RunStatus.SUCCEEDED


async def test_denied_tool_is_not_executed_and_becomes_model_observation() -> None:
    call = _call()
    provider = FakeProvider(
        [
            [ToolCallAvailable(call), ModelCompleted(finish_reason="tool_calls")],
            ["I could not inspect the file.", ModelCompleted(finish_reason="stop")],
        ]
    )
    tool = FakeTool(ToolResult.success("private contents"))
    registry = ToolRegistry((tool,))
    runtime = AgentRuntime(
        provider,
        registry,
        FakeApprovalManager(ApprovalDecision.DENY),
        system_prompt="You are Vortex.",
    )

    events = [event async for event in runtime.run("Inspect this workspace")]

    tool_finished = next(event for event in events if isinstance(event, ToolCallFinished))
    assert tool_finished.result.error_code is ToolErrorCode.PERMISSION_DENIED
    assert tool.calls == []
    assert provider.requests[1][-1].content.startswith("Tool error [permission_denied]")
    assert isinstance(events[-1], RunFinished)
    assert events[-1].status is RunStatus.SUCCEEDED
    assert events[-1].tool_calls == 0


async def test_iteration_limit_stops_run_without_committing_partial_history() -> None:
    call = _call()
    provider = FakeProvider(
        [
            [ToolCallAvailable(call), ModelCompleted(finish_reason="tool_calls")],
            [ToolCallAvailable(_call("call-2")), ModelCompleted(finish_reason="tool_calls")],
            ["Best effort summary", ModelCompleted(finish_reason="stop")],
        ]
    )
    tool = FakeTool(ToolResult.success("observation"))
    runtime = _runtime(provider, tool, max_iterations=2)

    events = [event async for event in runtime.run("Keep inspecting")]

    finished = events[-1]
    assert isinstance(finished, RunFinished)
    assert finished.status is RunStatus.SUCCEEDED
    assert finished.reason is TerminationReason.BUDGET_FINALIZED
    assert finished.iterations == 3
    assert finished.tool_calls == 2
    assert finished.final_output == "Best effort summary"
    assert runtime.messages[-1] == Message(MessageRole.ASSISTANT, "Best effort summary")
    assert provider.tool_requests[-1] == ()


async def test_tool_call_limit_stops_before_executing_excess_call() -> None:
    provider = FakeProvider(
        [
            [ToolCallAvailable(_call("call-1")), ModelCompleted(finish_reason="tool_calls")],
            [ToolCallAvailable(_call("call-2")), ModelCompleted(finish_reason="tool_calls")],
            ["Budget-aware summary", ModelCompleted(finish_reason="stop")],
        ]
    )
    tool = FakeTool(ToolResult.success("observation"))
    runtime = _runtime(provider, tool, max_tool_calls=1)

    events = [event async for event in runtime.run("Inspect forever")]

    finished = events[-1]
    assert isinstance(finished, RunFinished)
    assert finished.status is RunStatus.SUCCEEDED
    assert finished.reason is TerminationReason.BUDGET_FINALIZED
    assert len(tool.calls) == 1
    assert finished.final_output == "Budget-aware summary"
    assert provider.requests[-1][-2].content.startswith("Tool error [execution_limit]")
    assert provider.tool_requests[-1] == ()


async def test_cancelled_run_emits_terminal_status_and_does_not_commit() -> None:
    provider = BlockingProvider()
    runtime = _runtime(provider)
    events = []

    async def consume() -> None:
        async for event in runtime.run("Wait forever"):
            events.append(event)

    task = asyncio.create_task(consume())
    await provider.started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    finished = next(event for event in events if isinstance(event, RunFinished))
    assert finished.status is RunStatus.CANCELLED
    assert finished.reason is TerminationReason.CANCELLED
    assert runtime.messages == (Message(MessageRole.SYSTEM, "You are Vortex."),)


async def test_model_error_emits_failed_status_and_does_not_commit() -> None:
    error = ModelError("private detail", user_message="Safe model error")
    runtime = _runtime(FakeProvider([], error=error))
    events = []

    with pytest.raises(ModelError, match="private detail"):
        async for event in runtime.run("Fail safely"):
            events.append(event)

    finished = next(event for event in events if isinstance(event, RunFinished))
    assert finished.status is RunStatus.FAILED
    assert finished.reason is TerminationReason.MODEL_ERROR
    assert runtime.messages == (Message(MessageRole.SYSTEM, "You are Vortex."),)


async def test_unexpected_runtime_error_emits_terminal_status_and_does_not_commit() -> None:
    provider = FakeProvider(
        [[ToolCallAvailable(_call()), ModelCompleted(finish_reason="tool_calls")]]
    )
    tool = FakeTool(ToolResult.success("private contents"))
    runtime = AgentRuntime(
        provider,
        ToolRegistry((tool,)),
        _FailingApprovalManager(),
        system_prompt="You are Vortex.",
    )
    events = []

    with pytest.raises(RuntimeError, match="approval callback failed"):
        async for event in runtime.run("Inspect the workspace"):
            events.append(event)

    finished = next(event for event in events if isinstance(event, RunFinished))
    assert finished.status is RunStatus.FAILED
    assert finished.reason is TerminationReason.RUNTIME_ERROR
    assert tool.calls == []
    assert runtime.messages == (Message(MessageRole.SYSTEM, "You are Vortex."),)


async def test_successive_user_runs_reuse_only_committed_history() -> None:
    provider = FakeProvider([["First answer"], ["Second answer"]])
    runtime = _runtime(provider)

    _ = [event async for event in runtime.run("First question")]
    _ = [event async for event in runtime.run("Follow up")]

    assert provider.requests[1] == runtime.messages[:4]
    assert [(message.role, message.content) for message in runtime.messages] == [
        (MessageRole.SYSTEM, "You are Vortex."),
        (MessageRole.USER, "First question"),
        (MessageRole.ASSISTANT, "First answer"),
        (MessageRole.USER, "Follow up"),
        (MessageRole.ASSISTANT, "Second answer"),
    ]
