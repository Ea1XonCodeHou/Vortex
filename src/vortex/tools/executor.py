"""统一工具执行边界。"""

import asyncio
import logging
import time
from dataclasses import dataclass

from pydantic import ValidationError

from vortex.domain.tools import ToolCall, ToolErrorCode, ToolResult
from vortex.tools.base import ToolPreparation
from vortex.tools.errors import ToolInvocationError
from vortex.tools.registry import ToolRegistry

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ToolExecution:
    """工具结果及其单调时钟耗时。"""

    result: ToolResult
    elapsed_ms: int


@dataclass(frozen=True, slots=True)
class ToolPreparationExecution:
    """工具准备阶段的结果；失败时不会进入审批或执行。"""

    preparation: ToolPreparation | None
    error: ToolResult | None
    elapsed_ms: int

    def __post_init__(self) -> None:
        if (self.preparation is None) == (self.error is None):
            raise ValueError("Tool preparation requires exactly one result")


class ToolExecutor:
    """负责工具查找、超时和异常安全转换。"""

    def __init__(self, registry: ToolRegistry, *, timeout_seconds: float = 15.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("Tool timeout must be positive")
        self._registry = registry
        self._timeout_seconds = timeout_seconds

    async def execute(self, call: ToolCall) -> ToolExecution:
        """准备并执行一次调用，供不涉及审批的内部场景使用。"""
        prepared = await self.prepare(call)
        if prepared.error is not None:
            return ToolExecution(prepared.error, prepared.elapsed_ms)
        assert prepared.preparation is not None
        return await self.execute_prepared(prepared.preparation)

    async def prepare(self, call: ToolCall) -> ToolPreparationExecution:
        """解析并校验调用，但不得产生外部副作用。"""
        started = time.monotonic()
        tool = self._registry.get(call.name)
        if tool is None:
            return self._preparation_error(
                started,
                ToolResult.failure(
                    f"Unknown tool: {call.name}",
                    ToolErrorCode.UNKNOWN_TOOL,
                ),
            )

        try:
            preparation = await asyncio.wait_for(
                tool.prepare(call),
                timeout=self._timeout_seconds,
            )
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            error = ToolResult.failure(
                f"Tool timed out after {self._timeout_seconds:g} seconds.",
                ToolErrorCode.TIMEOUT,
            )
        except ValidationError as exc:
            error = ToolResult.failure(
                _validation_message(call, exc),
                ToolErrorCode.INVALID_ARGUMENTS,
            )
        except ToolInvocationError as exc:
            error = ToolResult.failure(str(exc), exc.code)
        except OSError:
            error = ToolResult.failure(
                "The operating system could not complete this tool call.",
                ToolErrorCode.EXECUTION_ERROR,
            )
        except Exception:
            log.exception(
                "Unexpected tool preparation failure tool=%s call_id=%s",
                call.name,
                call.id,
            )
            error = ToolResult.failure(
                "The tool failed unexpectedly.",
                ToolErrorCode.EXECUTION_ERROR,
            )
        else:
            elapsed_ms = max(0, int((time.monotonic() - started) * 1000))
            return ToolPreparationExecution(preparation, None, elapsed_ms)
        return self._preparation_error(started, error)

    async def execute_prepared(self, preparation: ToolPreparation) -> ToolExecution:
        """执行已经通过准备与外部审批的工具调用。"""
        started = time.monotonic()
        tool = self._registry.get(preparation.call.name)
        if tool is None:
            return self._result(
                started,
                ToolResult.failure(
                    f"Unknown tool: {preparation.call.name}",
                    ToolErrorCode.UNKNOWN_TOOL,
                ),
            )

        try:
            timeout = preparation.execution_timeout_seconds or self._timeout_seconds
            result = await asyncio.wait_for(
                tool.invoke_prepared(preparation),
                timeout=timeout,
            )
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            result = ToolResult.failure(
                f"Tool timed out after {timeout:g} seconds.",
                ToolErrorCode.TIMEOUT,
            )
        except ValidationError as exc:
            result = ToolResult.failure(
                _validation_message(preparation.call, exc),
                ToolErrorCode.INVALID_ARGUMENTS,
            )
        except ToolInvocationError as exc:
            result = ToolResult.failure(str(exc), exc.code)
        except OSError:
            result = ToolResult.failure(
                "The operating system could not complete this tool call.",
                ToolErrorCode.EXECUTION_ERROR,
            )
        except Exception:
            log.exception(
                "Unexpected tool failure tool=%s call_id=%s",
                preparation.call.name,
                preparation.call.id,
            )
            result = ToolResult.failure(
                "The tool failed unexpectedly.",
                ToolErrorCode.EXECUTION_ERROR,
            )
        return self._result(started, result)

    @staticmethod
    def _result(started: float, result: ToolResult) -> ToolExecution:
        elapsed_ms = max(0, int((time.monotonic() - started) * 1000))
        return ToolExecution(result=result, elapsed_ms=elapsed_ms)

    @staticmethod
    def _preparation_error(started: float, error: ToolResult) -> ToolPreparationExecution:
        elapsed_ms = max(0, int((time.monotonic() - started) * 1000))
        return ToolPreparationExecution(None, error, elapsed_ms)


def _validation_message(call: ToolCall, exc: ValidationError) -> str:
    """生成不包含原始输入值的简洁参数错误。"""
    errors = exc.errors(include_url=False, include_context=False, include_input=False)
    details = []
    for error in errors[:3]:
        location = ".".join(str(part) for part in error["loc"])
        details.append(f"{location}: {error['msg']}" if location else str(error["msg"]))
    sections = [
        "Phase: argument_validation",
        "Executed: false",
        f"Tool: {call.name}",
        "Invalid arguments: " + "; ".join(details),
    ]
    if call.name == "run_command" and any(error["loc"] == ("command",) for error in errors):
        sections.extend(
            (
                "Expected: command must be a JSON array of strings.",
                'Valid example: {"command":["python3","--version"]}',
                "Do not JSON-encode the array inside a string.",
            )
        )
    return "\n".join(sections)
