"""受控命令执行工具的进程、安全和输出边界测试。"""

import asyncio
import sys
from pathlib import Path

import pytest

from vortex.domain.tools import ToolCall, ToolErrorCode
from vortex.tools.builtin.run_command import RunCommandTool
from vortex.tools.executor import ToolExecutor
from vortex.tools.registry import ToolRegistry
from vortex.tools.workspace import Workspace


def _call(
    command: list[str],
    *,
    cwd: str = ".",
    timeout_seconds: int = 5,
) -> ToolCall:
    return ToolCall(
        id="command-1",
        name="run_command",
        arguments={
            "command": command,
            "cwd": cwd,
            "timeout_seconds": timeout_seconds,
        },
    )


def _executor(tmp_path: Path) -> ToolExecutor:
    tool = RunCommandTool(Workspace(tmp_path))
    return ToolExecutor(ToolRegistry((tool,)), timeout_seconds=1)


async def test_command_runs_without_shell_in_requested_workspace(tmp_path: Path) -> None:
    nested = tmp_path / "project"
    nested.mkdir()
    executor = _executor(tmp_path)
    call = _call(
        [sys.executable, "-c", "from pathlib import Path; print(Path.cwd().name)"],
        cwd="project",
    )

    prepared = await executor.prepare(call)
    assert prepared.preparation is not None
    assert f"Command: {sys.executable}" in prepared.preparation.approval_preview
    assert "Shell interpretation: disabled" in prepared.preparation.approval_preview

    execution = await executor.execute_prepared(prepared.preparation)

    assert execution.result.is_error is False
    assert "Phase: process_execution" in execution.result.content
    assert "Executed: true" in execution.result.content
    assert f"Command: {sys.executable}" in execution.result.content
    assert "Exit code: 0" in execution.result.content
    assert "stdout:\nproject" in execution.result.content


async def test_nonzero_exit_is_a_recoverable_observation(tmp_path: Path) -> None:
    execution = await _executor(tmp_path).execute(
        _call(
            [
                sys.executable,
                "-c",
                "import sys; print('verification failed', file=sys.stderr); sys.exit(7)",
            ]
        )
    )

    assert execution.result.error_code is ToolErrorCode.COMMAND_FAILED
    assert "Exit code: 7" in execution.result.content
    assert "stderr:\nverification failed" in execution.result.content


async def test_json_encoded_argv_is_safely_normalized(tmp_path: Path) -> None:
    executor = _executor(tmp_path)
    call = ToolCall(
        id="command-1",
        name="run_command",
        arguments={"command": f'["{sys.executable}","--version"]'},
    )

    prepared = await executor.prepare(call)

    assert prepared.error is None
    assert prepared.preparation is not None
    assert "Normalized input:" in prepared.preparation.approval_preview
    execution = await executor.execute_prepared(prepared.preparation)
    assert execution.result.is_error is False
    assert "Input normalization: JSON-encoded argv converted to an array." in (
        execution.result.content
    )


async def test_plain_command_string_is_rejected_with_actionable_validation(tmp_path: Path) -> None:
    call = ToolCall(
        id="command-1",
        name="run_command",
        arguments={"command": "python3 --version"},
    )

    execution = await _executor(tmp_path).execute(call)

    assert execution.result.error_code is ToolErrorCode.INVALID_ARGUMENTS
    assert "Phase: argument_validation" in execution.result.content
    assert "Executed: false" in execution.result.content
    assert "Expected: command must be a JSON array of strings." in execution.result.content
    assert '{"command":["python3","--version"]}' in execution.result.content


async def test_shell_metacharacters_remain_literal_arguments(tmp_path: Path) -> None:
    marker = tmp_path / "injected.txt"
    literal = "; touch injected.txt && echo unsafe"
    execution = await _executor(tmp_path).execute(
        _call(
            [
                sys.executable,
                "-c",
                "import sys; print(sys.argv[1])",
                literal,
            ]
        )
    )

    assert execution.result.is_error is False
    assert literal in execution.result.content
    assert marker.exists() is False


async def test_command_timeout_stops_process_and_returns_output(tmp_path: Path) -> None:
    execution = await _executor(tmp_path).execute(
        _call(
            [
                sys.executable,
                "-c",
                "import time; print('started', flush=True); time.sleep(30)",
            ],
            timeout_seconds=1,
        )
    )

    assert execution.result.error_code is ToolErrorCode.TIMEOUT
    assert "Timed out after 1s" in execution.result.content
    assert "stdout:\nstarted" in execution.result.content


async def test_cancellation_terminates_process_group(tmp_path: Path) -> None:
    marker = tmp_path / "should-not-exist.txt"
    executor = _executor(tmp_path)
    prepared = await executor.prepare(
        _call(
            [
                sys.executable,
                "-c",
                (
                    "import pathlib,time; time.sleep(1); "
                    "pathlib.Path('should-not-exist.txt').write_text('late')"
                ),
            ]
        )
    )
    assert prepared.preparation is not None
    task = asyncio.create_task(executor.execute_prepared(prepared.preparation))
    await asyncio.sleep(0.1)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(1.1)

    assert marker.exists() is False


async def test_large_output_is_bounded_with_head_and_tail(tmp_path: Path) -> None:
    execution = await _executor(tmp_path).execute(
        _call(
            [
                sys.executable,
                "-c",
                "print('HEAD' + ('x' * 40000) + 'TAIL')",
            ]
        )
    )

    assert execution.result.is_error is False
    assert "HEAD" in execution.result.content
    assert "TAIL" in execution.result.content
    assert "output bytes omitted" in execution.result.content
    assert len(execution.result.content) < 26_000


async def test_working_directory_cannot_escape_workspace(tmp_path: Path) -> None:
    execution = await _executor(tmp_path).execute(
        _call([sys.executable, "-c", "print('unsafe')"], cwd="..")
    )

    assert execution.result.error_code is ToolErrorCode.ACCESS_DENIED


async def test_sensitive_environment_values_are_not_forwarded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("VORTEX_TEST_SECRET_TOKEN", "must-not-leak")
    execution = await _executor(tmp_path).execute(
        _call(
            [
                sys.executable,
                "-c",
                "import os; print(os.getenv('VORTEX_TEST_SECRET_TOKEN', 'missing'))",
            ]
        )
    )

    assert "stdout:\nmissing" in execution.result.content
    assert "must-not-leak" not in execution.result.content
