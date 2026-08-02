"""工具执行过程中可安全归一化的异常。"""

from vortex.domain.tools import ToolErrorCode


class ToolInvocationError(RuntimeError):
    """携带稳定错误类别的预期工具错误。"""

    def __init__(self, message: str, code: ToolErrorCode) -> None:
        super().__init__(message)
        self.code = code
