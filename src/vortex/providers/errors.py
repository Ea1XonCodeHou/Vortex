"""模型调用错误的稳定分类。"""


class ModelError(RuntimeError):
    """可安全呈现给交互层的模型错误。"""

    def __init__(self, message: str, *, user_message: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.user_message = user_message
        self.retryable = retryable


class ModelProtocolError(ModelError):
    """供应商响应不满足 Vortex 所需协议。"""
