"""在当前工作区内执行经过逐次审批的非交互命令。"""

import asyncio
import json
import os
import shlex
import signal
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, cast

from pydantic import BaseModel, ConfigDict, Field

from vortex.domain.tools import ToolCall, ToolDefinition, ToolErrorCode, ToolResult, ToolRisk
from vortex.tools.base import BaseTool, ToolPreparation
from vortex.tools.errors import ToolInvocationError
from vortex.tools.workspace import Workspace

_MAX_ARGUMENTS = 64
_MAX_ARGUMENT_LENGTH = 4_096
_MAX_CAPTURE_BYTES = 24 * 1024
_CAPTURE_HEAD_BYTES = 16 * 1024
_PROCESS_STOP_GRACE_SECONDS = 2.0
_DEFAULT_TIMEOUT_SECONDS = 120
_MAX_TIMEOUT_SECONDS = 300
_SENSITIVE_ENV_MARKERS = (
    "ACCESS_KEY",
    "API_KEY",
    "AUTH",
    "AUTH_TOKEN",
    "COOKIE",
    "CREDENTIAL",
    "DEEPSEEK",
    "PASSWORD",
    "PASSWD",
    "PRIVATE_KEY",
    "SECRET",
    "TOKEN",
    "VORTEX",
)

CommandArgument = Annotated[str, Field(max_length=_MAX_ARGUMENT_LENGTH)]


class RunCommandArguments(BaseModel):
    """一次非 Shell 子进程执行参数。"""

    model_config = ConfigDict(extra="forbid")

    command: list[CommandArgument] = Field(min_length=1, max_length=_MAX_ARGUMENTS)
    cwd: str = Field(default=".", min_length=1, max_length=1_000)
    timeout_seconds: int = Field(
        default=_DEFAULT_TIMEOUT_SECONDS,
        ge=1,
        le=_MAX_TIMEOUT_SECONDS,
    )


@dataclass(frozen=True, slots=True)
class _PreparedCommand:
    command: tuple[str, ...]
    cwd: Path
    display_cwd: str
    timeout_seconds: int
    normalized_json_array: bool


@dataclass(slots=True)
class _BoundedCapture:
    """持续排空管道，同时只保留输出头尾。"""

    head: bytearray
    tail: bytearray
    total_bytes: int = 0

    @classmethod
    def create(cls) -> "_BoundedCapture":
        return cls(bytearray(), bytearray())

    def add(self, chunk: bytes) -> None:
        self.total_bytes += len(chunk)
        head_remaining = max(0, _CAPTURE_HEAD_BYTES - len(self.head))
        if head_remaining:
            self.head.extend(chunk[:head_remaining])
        tail_source = bytes(self.tail) + chunk
        tail_limit = _MAX_CAPTURE_BYTES - _CAPTURE_HEAD_BYTES
        self.tail = bytearray(tail_source[-tail_limit:])

    def render(self) -> str:
        if self.total_bytes <= _MAX_CAPTURE_BYTES:
            combined = bytes(self.head)
            if self.total_bytes > len(self.head):
                combined += bytes(self.tail)[-(self.total_bytes - len(self.head)) :]
            return combined.decode("utf-8", errors="replace")
        omitted = self.total_bytes - len(self.head) - len(self.tail)
        return (
            self.head.decode("utf-8", errors="replace")
            + f"\n... {omitted} output bytes omitted ...\n"
            + self.tail.decode("utf-8", errors="replace")
        )


class RunCommandTool(BaseTool):
    """执行 argv 数组，不经过隐式 Shell 解析。"""

    definition = ToolDefinition(
        name="run_command",
        description=(
            "Run one non-interactive command in the current workspace and return its exit code, "
            "stdout, and stderr. Pass command as a JSON argv array of strings, for example "
            '{"command":["python3","--version"]}. Never JSON-encode that array inside a '
            "string. Shell operators such as pipes, redirects, "
            "and && are not interpreted. Use this to run focused tests, linters, type checks, "
            "builds, and read-only version-control inspection after examining the project's "
            "own instructions and manifests. Every invocation requires user approval. Commands "
            "may execute project code or modify files, and their side effects are not included "
            "in apply_patch Revert. Do not use package installers, interactive programs, or "
            "shell interpreters unless the user explicitly requested them."
        ),
        input_schema=cast(dict[str, object], RunCommandArguments.model_json_schema()),
        risk=ToolRisk.EXECUTE,
    )

    def __init__(self, workspace: Workspace) -> None:
        self._workspace = workspace

    async def prepare(self, call: ToolCall) -> ToolPreparation:
        normalized_arguments, normalized_json_array = _normalize_arguments(call.arguments)
        params = RunCommandArguments.model_validate(normalized_arguments)
        if not params.command[0].strip():
            raise ToolInvocationError(
                "The command executable cannot be empty.",
                ToolErrorCode.INVALID_ARGUMENTS,
            )
        if any("\x00" in argument for argument in params.command):
            raise ToolInvocationError(
                "Command arguments cannot contain NUL bytes.",
                ToolErrorCode.INVALID_ARGUMENTS,
            )
        cwd = self._workspace.resolve(params.cwd)
        if not cwd.is_dir():
            raise ToolInvocationError(
                f"Command working directory is not a directory: {params.cwd}",
                ToolErrorCode.INVALID_ARGUMENTS,
            )
        prepared = _PreparedCommand(
            command=tuple(params.command),
            cwd=cwd,
            display_cwd=self._workspace.display(cwd),
            timeout_seconds=params.timeout_seconds,
            normalized_json_array=normalized_json_array,
        )
        preview = (
            f"Command: {shlex.join(prepared.command)}\n"
            f"Working directory: {prepared.display_cwd}\n"
            f"Timeout: {prepared.timeout_seconds}s\n"
            "Shell interpretation: disabled\n\n"
            "This command executes local code and may modify files. Command side effects are "
            "not included in Vortex Revert."
        )
        if prepared.normalized_json_array:
            preview = (
                "Normalized input: converted a JSON-encoded argv string into an argv array.\n"
                + preview
            )
        return ToolPreparation(
            call=call,
            approval_preview=preview,
            payload=prepared,
            execution_timeout_seconds=(
                prepared.timeout_seconds + (2 * _PROCESS_STOP_GRACE_SECONDS) + 2
            ),
        )

    async def invoke(self, arguments: Mapping[str, object]) -> ToolResult:
        call = ToolCall(id="direct", name=self.definition.name, arguments=dict(arguments))
        return await self.invoke_prepared(await self.prepare(call))

    async def invoke_prepared(self, preparation: ToolPreparation) -> ToolResult:
        if not isinstance(preparation.payload, _PreparedCommand):
            raise ToolInvocationError(
                "The prepared command payload is invalid.",
                ToolErrorCode.INVALID_ARGUMENTS,
            )
        prepared = preparation.payload
        try:
            process = await asyncio.create_subprocess_exec(
                *prepared.command,
                cwd=prepared.cwd,
                env=_sanitized_environment(),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
        except FileNotFoundError as exc:
            raise ToolInvocationError(
                f"Executable was not found: {prepared.command[0]}",
                ToolErrorCode.NOT_FOUND,
            ) from exc
        except PermissionError as exc:
            raise ToolInvocationError(
                f"Executable could not be started: {prepared.command[0]}",
                ToolErrorCode.ACCESS_DENIED,
            ) from exc

        assert process.stdout is not None
        assert process.stderr is not None
        stdout_task = asyncio.create_task(_drain_stream(process.stdout))
        stderr_task = asyncio.create_task(_drain_stream(process.stderr))
        timed_out = False
        return_code: int | None
        try:
            async with asyncio.timeout(prepared.timeout_seconds):
                return_code = await process.wait()
        except TimeoutError:
            timed_out = True
            await _stop_process(process)
            return_code = process.returncode
        except asyncio.CancelledError:
            await _stop_process(process)
            await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
            raise

        stdout_capture, stderr_capture = await asyncio.gather(stdout_task, stderr_task)
        output = _format_result(
            prepared,
            return_code,
            stdout_capture.render(),
            stderr_capture.render(),
            timed_out=timed_out,
        )
        if timed_out:
            return ToolResult.failure(output, ToolErrorCode.TIMEOUT)
        if return_code != 0:
            return ToolResult.failure(output, ToolErrorCode.COMMAND_FAILED)
        return ToolResult.success(output)


async def _drain_stream(stream: asyncio.StreamReader) -> _BoundedCapture:
    capture = _BoundedCapture.create()
    while chunk := await stream.read(8_192):
        capture.add(chunk)
    return capture


async def _stop_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    _signal_process(process, signal.SIGTERM)
    try:
        await asyncio.wait_for(process.wait(), timeout=_PROCESS_STOP_GRACE_SECONDS)
    except TimeoutError:
        _signal_process(process, signal.SIGKILL)
        await process.wait()


def _signal_process(process: asyncio.subprocess.Process, command_signal: signal.Signals) -> None:
    try:
        if os.name == "posix":
            os.killpg(process.pid, command_signal)
        elif command_signal is signal.SIGTERM:
            process.terminate()
        else:
            process.kill()
    except ProcessLookupError:
        return


def _sanitized_environment() -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not any(marker in key.upper() for marker in _SENSITIVE_ENV_MARKERS)
        and key.upper() not in {"DYLD_INSERT_LIBRARIES", "LD_PRELOAD", "PYTHONHOME", "PYTHONPATH"}
    }
    path_entries = [
        entry
        for entry in environment.get("PATH", os.defpath).split(os.pathsep)
        if entry and Path(entry).is_absolute()
    ]
    environment["PATH"] = os.pathsep.join(path_entries) or os.defpath
    environment.setdefault("LANG", "C.UTF-8")
    return environment


def _format_result(
    prepared: _PreparedCommand,
    return_code: int | None,
    stdout: str,
    stderr: str,
    *,
    timed_out: bool,
) -> str:
    status = (
        f"Timed out after {prepared.timeout_seconds}s" if timed_out else f"Exit code: {return_code}"
    )
    sections = [
        "Phase: process_execution",
        "Executed: true",
        f"Command: {shlex.join(prepared.command)}",
        status,
        f"Working directory: {prepared.display_cwd}",
    ]
    if prepared.normalized_json_array:
        sections.append("Input normalization: JSON-encoded argv converted to an array.")
    if stdout:
        sections.extend(("stdout:", stdout.rstrip()))
    if stderr:
        sections.extend(("stderr:", stderr.rstrip()))
    if not stdout and not stderr:
        sections.append("No output.")
    return "\n".join(sections)


def _normalize_arguments(arguments: Mapping[str, object]) -> tuple[dict[str, object], bool]:
    """仅修复明确的 JSON 数组字符串，不猜测或解析普通 Shell 命令。"""
    normalized = dict(arguments)
    command = normalized.get("command")
    if not isinstance(command, str):
        return normalized, False
    try:
        parsed: object = json.loads(command)
    except json.JSONDecodeError:
        return normalized, False
    if (
        not isinstance(parsed, list)
        or not parsed
        or not all(isinstance(item, str) for item in parsed)
    ):
        return normalized, False
    normalized["command"] = parsed
    return normalized, True


__all__ = ["RunCommandArguments", "RunCommandTool"]
