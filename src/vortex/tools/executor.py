"""统一工具执行边界。"""

import asyncio
import logging
import time
from dataclasses import dataclass

from pydantic import ValidationError

from vortex.domain.tools import ToolCall, ToolErrorCode, ToolResult
from vortex.tools.errors import ToolInvocationError
from vortex.tools.registry import ToolRegistry

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ToolExecution:
    """工具结果及其单调时钟耗时。"""

    result: ToolResult
    elapsed_ms: int


class ToolExecutor:
    """负责工具查找、超时和异常安全转换。"""

    def __init__(self, registry: ToolRegistry, *, timeout_seconds: float = 15.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("Tool timeout must be positive")
        self._registry = registry
        self._timeout_seconds = timeout_seconds

    async def execute(self, call: ToolCall) -> ToolExecution:
        """执行一次调用，并将可恢复错误转换成 ToolResult。"""
        started = time.monotonic()
        tool = self._registry.get(call.name)
        if tool is None:
            return self._result(
                started,
                ToolResult.failure(
                    f"Unknown tool: {call.name}",
                    ToolErrorCode.UNKNOWN_TOOL,
                ),
            )

        try:
            result = await asyncio.wait_for(
                tool.invoke(call.arguments),
                timeout=self._timeout_seconds,
            )
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            result = ToolResult.failure(
                f"Tool timed out after {self._timeout_seconds:g} seconds.",
                ToolErrorCode.TIMEOUT,
            )
        except ValidationError as exc:
            result = ToolResult.failure(
                _validation_message(exc),
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
                call.name,
                call.id,
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


def _validation_message(exc: ValidationError) -> str:
    """生成不包含原始输入值的简洁参数错误。"""
    errors = exc.errors(include_url=False, include_context=False, include_input=False)
    details = []
    for error in errors[:3]:
        location = ".".join(str(part) for part in error["loc"])
        details.append(f"{location}: {error['msg']}" if location else str(error["msg"]))
    return "Invalid tool arguments: " + "; ".join(details)
