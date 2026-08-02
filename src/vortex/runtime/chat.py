"""无持久化的首期对话运行时。"""

import asyncio
from collections.abc import AsyncIterator

from vortex.domain.messages import Message, MessageRole
from vortex.domain.model_events import ModelCompleted, ModelEvent, TextDelta
from vortex.providers.base import ModelProvider
from vortex.providers.errors import ModelProtocolError


class ChatBusyError(RuntimeError):
    """当前会话已有一个正在生成的回复。"""


class ChatService:
    """维护当前进程的消息历史并驱动单次模型生成。"""

    def __init__(self, provider: ModelProvider, *, system_prompt: str) -> None:
        self._provider = provider
        self._messages = [Message(MessageRole.SYSTEM, system_prompt)]
        self._generation_lock = asyncio.Lock()

    @property
    def model_name(self) -> str:
        return self._provider.model_name

    @property
    def messages(self) -> tuple[Message, ...]:
        """返回当前进程内已经完整提交的消息。"""
        return tuple(self._messages)

    async def stream_reply(self, user_text: str) -> AsyncIterator[ModelEvent]:
        """生成回复，并仅在完整结束后原子提交本轮消息。"""
        normalized_text = user_text.strip()
        if not normalized_text:
            raise ValueError("User message cannot be empty")
        if self._generation_lock.locked():
            raise ChatBusyError("A response is already being generated")

        async with self._generation_lock:
            user_message = Message(MessageRole.USER, normalized_text)
            request_messages = (*self._messages, user_message)
            response_parts: list[str] = []
            completed = False

            async for event in self._provider.stream(request_messages):
                if isinstance(event, TextDelta):
                    response_parts.append(event.text)
                elif isinstance(event, ModelCompleted):
                    completed = True
                yield event

            response_text = "".join(response_parts)
            if not completed or not response_text:
                raise ModelProtocolError(
                    "The provider stream ended without a complete text response",
                    user_message="DeepSeek returned an incomplete response. Please try again.",
                    retryable=True,
                )

            self._messages.extend(
                (
                    user_message,
                    Message(MessageRole.ASSISTANT, response_text),
                )
            )

    async def aclose(self) -> None:
        await self._provider.aclose()
