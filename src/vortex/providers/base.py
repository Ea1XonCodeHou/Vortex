"""模型供应商统一协议。"""

from collections.abc import AsyncIterator, Sequence
from typing import Protocol

from vortex.domain.messages import Message
from vortex.domain.model_events import ModelEvent


class ModelProvider(Protocol):
    """Chat Runtime 依赖的最小模型能力。"""

    @property
    def model_name(self) -> str:
        """返回当前请求使用的模型标识。"""
        ...

    def stream(self, messages: Sequence[Message]) -> AsyncIterator[ModelEvent]:
        """异步产生一次模型响应的标准事件。"""
        ...

    async def aclose(self) -> None:
        """关闭连接池等供应商资源。"""
        ...
