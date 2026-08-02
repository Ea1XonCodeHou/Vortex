"""不访问网络的确定性模型供应商。"""

import asyncio
from collections import deque
from collections.abc import AsyncIterator, Sequence

from vortex.domain.messages import Message
from vortex.domain.model_events import ModelCompleted, ModelEvent, TextDelta, TokenUsage
from vortex.providers.errors import ModelError


class FakeProvider:
    """按测试脚本逐轮返回文本分片。"""

    def __init__(
        self,
        responses: Sequence[Sequence[str]],
        *,
        error: ModelError | None = None,
    ) -> None:
        self._responses = deque(tuple(response) for response in responses)
        self._error = error
        self.requests: list[tuple[Message, ...]] = []
        self.closed = False

    @property
    def model_name(self) -> str:
        return "deepseek-v4-flash"

    async def stream(self, messages: Sequence[Message]) -> AsyncIterator[ModelEvent]:
        self.requests.append(tuple(messages))
        await asyncio.sleep(0)
        if self._error is not None:
            raise self._error
        if not self._responses:
            raise AssertionError("FakeProvider has no scripted response")

        response = self._responses.popleft()
        for part in response:
            yield TextDelta(part)
            await asyncio.sleep(0)
        yield ModelCompleted(
            finish_reason="stop",
            usage=TokenUsage(input_tokens=12, output_tokens=5, total_tokens=17),
        )

    async def aclose(self) -> None:
        self.closed = True


class BlockingProvider:
    """产生一个分片后持续等待，用于验证取消链路。"""

    def __init__(self) -> None:
        self.started = asyncio.Event()

    @property
    def model_name(self) -> str:
        return "deepseek-v4-flash"

    async def stream(self, messages: Sequence[Message]) -> AsyncIterator[ModelEvent]:
        del messages
        yield TextDelta("partial")
        self.started.set()
        await asyncio.Event().wait()

    async def aclose(self) -> None:
        return None
