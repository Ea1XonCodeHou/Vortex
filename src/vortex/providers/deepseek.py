"""DeepSeek Chat Completions 适配器。"""

import asyncio
from collections.abc import AsyncIterator, Sequence

import httpx
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    BadRequestError,
    RateLimitError,
)
from openai.types.chat import ChatCompletionMessageParam
from openai.types.chat.chat_completion_assistant_message_param import (
    ChatCompletionAssistantMessageParam,
)
from openai.types.chat.chat_completion_system_message_param import ChatCompletionSystemMessageParam
from openai.types.chat.chat_completion_user_message_param import ChatCompletionUserMessageParam

from vortex.domain.messages import Message, MessageRole
from vortex.domain.model_events import ModelCompleted, ModelEvent, TextDelta, TokenUsage
from vortex.providers.errors import ModelError


class DeepSeekProvider:
    """通过 OpenAI-compatible 协议访问 DeepSeek。"""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "deepseek-v4-flash",
        base_url: str = "https://api.deepseek.com",
        timeout_seconds: float = 180.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._model_name = model
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=httpx.Timeout(timeout_seconds, connect=10.0),
            max_retries=1,
            http_client=http_client,
        )

    @property
    def model_name(self) -> str:
        return self._model_name

    async def stream(self, messages: Sequence[Message]) -> AsyncIterator[ModelEvent]:
        """将 DeepSeek SSE 分片转换成 Vortex 模型事件。"""
        api_messages = [_to_api_message(message) for message in messages]
        finish_reason = "unknown"
        usage: TokenUsage | None = None

        try:
            stream = await self._client.chat.completions.create(
                model=self.model_name,
                messages=api_messages,
                stream=True,
                stream_options={"include_usage": True},
                extra_body={"thinking": {"type": "disabled"}},
            )
            try:
                async for chunk in stream:
                    if chunk.usage is not None:
                        usage = TokenUsage(
                            input_tokens=chunk.usage.prompt_tokens,
                            output_tokens=chunk.usage.completion_tokens,
                            total_tokens=chunk.usage.total_tokens,
                        )

                    # usage 尾块的 choices 为空，不能直接访问 choices[0]
                    for choice in chunk.choices:
                        if choice.delta.content:
                            yield TextDelta(choice.delta.content)
                        if choice.finish_reason is not None:
                            finish_reason = choice.finish_reason
            finally:
                await stream.close()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise _translate_error(exc) from exc

        yield ModelCompleted(finish_reason=finish_reason, usage=usage)

    async def aclose(self) -> None:
        await self._client.close()


def _to_api_message(message: Message) -> ChatCompletionMessageParam:
    """按具体角色构造 SDK TypedDict，避免供应商类型渗入领域层。"""
    if message.role is MessageRole.SYSTEM:
        system_message: ChatCompletionSystemMessageParam = {
            "role": "system",
            "content": message.content,
        }
        return system_message
    if message.role is MessageRole.USER:
        user_message: ChatCompletionUserMessageParam = {
            "role": "user",
            "content": message.content,
        }
        return user_message

    assistant_message: ChatCompletionAssistantMessageParam = {
        "role": "assistant",
        "content": message.content,
    }
    return assistant_message


def _translate_error(exc: Exception) -> ModelError:
    """将 SDK 异常收敛为不会泄露响应细节的用户错误。"""
    if isinstance(exc, AuthenticationError):
        return ModelError(
            str(exc),
            user_message="DeepSeek authentication failed. Check DEEPSEEK_API_KEY in .env.",
        )
    if isinstance(exc, RateLimitError):
        return ModelError(
            str(exc),
            user_message="DeepSeek rate limit reached. Please try again shortly.",
            retryable=True,
        )
    if isinstance(exc, BadRequestError):
        return ModelError(
            str(exc),
            user_message="DeepSeek rejected the request. Check the model configuration.",
        )
    if isinstance(exc, APITimeoutError):
        return ModelError(
            str(exc),
            user_message="DeepSeek did not respond before the request timed out.",
            retryable=True,
        )
    if isinstance(exc, APIConnectionError):
        return ModelError(
            str(exc),
            user_message="Unable to connect to DeepSeek. Check your network and try again.",
            retryable=True,
        )
    if isinstance(exc, APIStatusError):
        if exc.status_code == 402:
            user_message = "The DeepSeek account has insufficient balance."
            retryable = False
        elif exc.status_code in {500, 503}:
            user_message = "DeepSeek is temporarily unavailable. Please try again shortly."
            retryable = True
        else:
            user_message = f"DeepSeek returned an unexpected HTTP {exc.status_code} error."
            retryable = False
        return ModelError(str(exc), user_message=user_message, retryable=retryable)
    if isinstance(exc, ModelError):
        return exc
    return ModelError(
        str(exc),
        user_message="The model response failed unexpectedly. Please try again.",
    )
