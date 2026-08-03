"""纯内存单 Agent Loop 的确定性测试。"""

import asyncio
import sys
from pathlib import Path

import pytest

from tests.support.fake_approval import FakeApprovalManager
from tests.support.fake_provider import BlockingProvider, FakeProvider
from tests.support.fake_tool import FakeTool
from vortex.domain.messages import Message, MessageRole
from vortex.domain.model_events import ModelCompleted, ModelEvent, TokenUsage, ToolCallAvailable
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
from vortex.domain.tools import ToolCall, ToolErrorCode, ToolResult, ToolRisk
from vortex.providers.errors import ModelError
from vortex.runtime.agent import AgentRuntime
from vortex.tools.builtin.apply_patch import ApplyPatchTool
from vortex.tools.builtin.run_command import RunCommandTool
from vortex.tools.changes import TurnChangeTracker
from vortex.tools.registry import ToolRegistry
from vortex.tools.workspace import Workspace


def _call(identifier: str = "call-1") -> ToolCall:
    return ToolCall(id=identifier, name="inspect", arguments={"path": "README.md"})


class _FailingApprovalManager:
    async def authorize(self, request: ToolApprovalRequest) -> ApprovalOutcome:
        del request
        raise RuntimeError("approval callback failed")


class _RiskApprovalManager:
    def __init__(self) -> None:
        self.requests: list[ToolApprovalRequest] = []

    async def authorize(self, request: ToolApprovalRequest) -> ApprovalOutcome:
        self.requests.append(request)
        decision = (
            ApprovalDecision.ALLOW_TURN
            if request.risk is ToolRisk.WRITE
            else ApprovalDecision.ALLOW_ONCE
        )
        return ApprovalOutcome(decision)


def _runtime(
    provider: FakeProvider | BlockingProvider,
    tool: FakeTool | None = None,
    *,
    max_iterations: int | None = None,
    max_tools_per_iteration: int = 8,
    max_stalled_iterations: int = 3,
    max_consecutive_tool_errors: int = 6,
) -> AgentRuntime:
    registry = ToolRegistry((tool,)) if tool is not None else ToolRegistry()
    return AgentRuntime(
        provider,
        registry,
        FakeApprovalManager(),
        system_prompt="You are Vortex.",
        max_iterations=max_iterations,
        max_tools_per_iteration=max_tools_per_iteration,
        max_stalled_iterations=max_stalled_iterations,
        max_consecutive_tool_errors=max_consecutive_tool_errors,
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
    assert finished.reason is TerminationReason.SAFETY_FINALIZED
    assert finished.iterations == 3
    assert finished.tool_calls == 2
    assert finished.final_output == "Best effort summary"
    assert runtime.messages[-1] == Message(MessageRole.ASSISTANT, "Best effort summary")
    assert provider.tool_requests[-1] == ()


async def test_per_step_limit_defers_excess_call_without_stopping_run() -> None:
    provider = FakeProvider(
        [
            [
                ToolCallAvailable(_call("call-1")),
                ToolCallAvailable(_call("call-2")),
                ModelCompleted(finish_reason="tool_calls"),
            ],
            ["Complete summary", ModelCompleted(finish_reason="stop")],
        ]
    )
    tool = FakeTool(ToolResult.success("observation"))
    runtime = _runtime(provider, tool, max_tools_per_iteration=1)

    events = [event async for event in runtime.run("Inspect the workspace")]

    finished = events[-1]
    assert isinstance(finished, RunFinished)
    assert finished.status is RunStatus.SUCCEEDED
    assert finished.reason is TerminationReason.COMPLETED
    assert len(tool.calls) == 1
    assert finished.final_output == "Complete summary"
    assert provider.requests[1][-1].content.startswith("Tool error [execution_limit]")
    assert provider.tool_requests[-1] != ()


async def test_progressing_run_is_not_stopped_by_total_tool_call_count() -> None:
    tool_rounds = 70
    responses: list[list[str | ModelEvent]] = [
        [
            ToolCallAvailable(
                ToolCall(
                    id=f"call-{index}",
                    name="inspect",
                    arguments={"path": f"file-{index}.py"},
                )
            ),
            ModelCompleted(finish_reason="tool_calls"),
        ]
        for index in range(tool_rounds)
    ]
    responses.append(["Long task complete", ModelCompleted(finish_reason="stop")])
    provider = FakeProvider(responses)
    tool = FakeTool(ToolResult.success("new evidence"))
    runtime = _runtime(provider, tool)

    events = [event async for event in runtime.run("Inspect a large repository")]

    finished = events[-1]
    assert isinstance(finished, RunFinished)
    assert finished.status is RunStatus.SUCCEEDED
    assert finished.reason is TerminationReason.COMPLETED
    assert finished.iterations == tool_rounds + 1
    assert finished.tool_calls == tool_rounds
    assert len(tool.calls) == tool_rounds


async def test_repeated_observations_trigger_safety_finalization() -> None:
    provider = FakeProvider(
        [
            [ToolCallAvailable(_call("call-1")), ModelCompleted(finish_reason="tool_calls")],
            [ToolCallAvailable(_call("call-2")), ModelCompleted(finish_reason="tool_calls")],
            [ToolCallAvailable(_call("call-3")), ModelCompleted(finish_reason="tool_calls")],
            ["I could not make further progress.", ModelCompleted(finish_reason="stop")],
        ]
    )
    tool = FakeTool(ToolResult.success("same observation"))
    runtime = _runtime(provider, tool, max_stalled_iterations=2)

    events = [event async for event in runtime.run("Inspect repeatedly")]

    finished = events[-1]
    assert isinstance(finished, RunFinished)
    assert finished.status is RunStatus.SUCCEEDED
    assert finished.reason is TerminationReason.SAFETY_FINALIZED
    assert finished.tool_calls == 3
    assert provider.tool_requests[-1] == ()


async def test_consecutive_control_errors_trigger_safety_finalization() -> None:
    provider = FakeProvider(
        [
            [ToolCallAvailable(_call("call-1")), ModelCompleted(finish_reason="tool_calls")],
            [ToolCallAvailable(_call("call-2")), ModelCompleted(finish_reason="tool_calls")],
            ["The requested files were unavailable.", ModelCompleted(finish_reason="stop")],
        ]
    )
    tool = FakeTool(ToolResult.failure("Invalid arguments", ToolErrorCode.INVALID_ARGUMENTS))
    runtime = _runtime(provider, tool, max_consecutive_tool_errors=2)

    events = [event async for event in runtime.run("Inspect unavailable files")]

    finished = events[-1]
    assert isinstance(finished, RunFinished)
    assert finished.status is RunStatus.SUCCEEDED
    assert finished.reason is TerminationReason.SAFETY_FINALIZED
    assert finished.tool_calls == 2


async def test_novel_command_failures_remain_diagnostic_progress() -> None:
    diagnostic_rounds = 8
    responses: list[list[str | ModelEvent]] = [
        [
            ToolCallAvailable(
                ToolCall(
                    id=f"command-{index}",
                    name="inspect",
                    arguments={"path": f"check-{index}"},
                )
            ),
            ModelCompleted(finish_reason="tool_calls"),
        ]
        for index in range(diagnostic_rounds)
    ]
    responses.append(["Diagnosis complete", ModelCompleted(finish_reason="stop")])
    provider = FakeProvider(responses)
    tool = FakeTool(ToolResult.failure("Exit code: 1", ToolErrorCode.COMMAND_FAILED))
    runtime = _runtime(provider, tool)

    events = [event async for event in runtime.run("Diagnose changing failures")]

    finished = events[-1]
    assert isinstance(finished, RunFinished)
    assert finished.status is RunStatus.SUCCEEDED
    assert finished.reason is TerminationReason.COMPLETED
    assert finished.tool_calls == diagnostic_rounds


async def test_safety_finalization_rejects_tool_protocol_artifacts() -> None:
    provider = FakeProvider(
        [
            [ToolCallAvailable(_call()), ModelCompleted(finish_reason="tool_calls")],
            [
                '<|DSML|tool_calls><|DSML|invoke name="read_file">',
                ModelCompleted(finish_reason="stop"),
            ],
        ]
    )
    runtime = _runtime(provider, FakeTool(ToolResult.success("evidence")), max_iterations=1)

    events = [event async for event in runtime.run("Inspect and stop safely")]

    assert not any(
        isinstance(event, AssistantTextDelta) and "DSML" in event.text for event in events
    )
    finished = events[-1]
    assert isinstance(finished, RunFinished)
    assert finished.status is RunStatus.LIMIT_REACHED
    assert finished.reason is TerminationReason.MAX_ITERATIONS


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


async def test_write_tool_is_previewed_tracked_and_revertible(tmp_path: Path) -> None:
    target = tmp_path / "example.py"
    target.write_text("value = 1\n", encoding="utf-8")
    call = ToolCall(
        id="patch-1",
        name="apply_patch",
        arguments={
            "path": "example.py",
            "edits": [{"old_text": "value = 1", "new_text": "value = 2"}],
        },
    )
    provider = FakeProvider(
        [
            [ToolCallAvailable(call), ModelCompleted(finish_reason="tool_calls")],
            ["Updated and verified.", ModelCompleted(finish_reason="stop")],
        ]
    )
    workspace = Workspace(tmp_path)
    tracker = TurnChangeTracker(workspace)
    tool = ApplyPatchTool(workspace, tracker)
    approvals = FakeApprovalManager(ApprovalDecision.ALLOW_TURN)
    runtime = AgentRuntime(
        provider,
        ToolRegistry((tool,)),
        approvals,
        system_prompt="You are Vortex.",
        change_tracker=tracker,
    )

    events = [event async for event in runtime.run("Update the value")]
    finished = events[-1]

    assert isinstance(finished, RunFinished)
    assert target.read_text(encoding="utf-8") == "value = 2\n"
    assert approvals.requests[0].allowed_decisions == (
        ApprovalDecision.ALLOW_TURN,
        ApprovalDecision.DENY,
    )
    assert "+value = 2" in approvals.requests[0].preview
    assert finished.changes is not None
    assert finished.changes.files[0].path == "example.py"

    result = await runtime.revert_latest_turn(finished.run_id)
    assert result.status.value == "reverted"
    assert target.read_text(encoding="utf-8") == "value = 1\n"


async def test_agent_uses_failed_verification_to_fix_and_rerun(tmp_path: Path) -> None:
    target = tmp_path / "example.py"
    target.write_text("state = 'A'\n", encoding="utf-8")
    first_patch = ToolCall(
        id="patch-1",
        name="apply_patch",
        arguments={
            "path": "example.py",
            "edits": [{"old_text": "'A'", "new_text": "'B'"}],
        },
    )
    failed_check = ToolCall(
        id="command-1",
        name="run_command",
        arguments={
            "command": [
                sys.executable,
                "-c",
                "from pathlib import Path; assert \"'C'\" in Path('example.py').read_text()",
            ],
        },
    )
    corrective_patch = ToolCall(
        id="patch-2",
        name="apply_patch",
        arguments={
            "path": "example.py",
            "edits": [{"old_text": "'B'", "new_text": "'C'"}],
        },
    )
    passing_check = ToolCall(
        id="command-2",
        name="run_command",
        arguments=failed_check.arguments,
    )
    provider = FakeProvider(
        [
            [ToolCallAvailable(first_patch), ModelCompleted(finish_reason="tool_calls")],
            [ToolCallAvailable(failed_check), ModelCompleted(finish_reason="tool_calls")],
            [ToolCallAvailable(corrective_patch), ModelCompleted(finish_reason="tool_calls")],
            [ToolCallAvailable(passing_check), ModelCompleted(finish_reason="tool_calls")],
            ["Fixed and verified.", ModelCompleted(finish_reason="stop")],
        ]
    )
    workspace = Workspace(tmp_path)
    tracker = TurnChangeTracker(workspace)
    approvals = _RiskApprovalManager()
    runtime = AgentRuntime(
        provider,
        ToolRegistry((ApplyPatchTool(workspace, tracker), RunCommandTool(workspace))),
        approvals,
        system_prompt="You are Vortex.",
        change_tracker=tracker,
    )

    events = [event async for event in runtime.run("Set the expected state and verify it")]
    finished = events[-1]

    assert isinstance(finished, RunFinished)
    assert finished.status is RunStatus.SUCCEEDED
    assert finished.tool_calls == 4
    assert finished.final_output == "Fixed and verified."
    assert target.read_text(encoding="utf-8") == "state = 'C'\n"
    assert "Tool error [command_failed]" in provider.requests[2][-1].content
    assert "Exit code: 0" in provider.requests[4][-1].content
    assert [request.risk for request in approvals.requests] == [
        ToolRisk.WRITE,
        ToolRisk.EXECUTE,
        ToolRisk.WRITE,
        ToolRisk.EXECUTE,
    ]
    assert all(
        request.allowed_decisions
        == (
            ApprovalDecision.ALLOW_ONCE,
            ApprovalDecision.DENY,
        )
        for request in approvals.requests
        if request.risk is ToolRisk.EXECUTE
    )
    assert finished.changes is not None
    assert "-state = 'A'" in finished.changes.diff
    assert "+state = 'C'" in finished.changes.diff
