"""DeepSeek Chat Completions 适配器。"""

import asyncio
import json
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import cast

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
from openai.types.chat import (
    ChatCompletionMessageParam,
    ChatCompletionMessageToolCallParam,
    ChatCompletionToolMessageParam,
    ChatCompletionToolParam,
)
from openai.types.chat.chat_completion_assistant_message_param import (
    ChatCompletionAssistantMessageParam,
)
from openai.types.chat.chat_completion_system_message_param import ChatCompletionSystemMessageParam
from openai.types.chat.chat_completion_user_message_param import ChatCompletionUserMessageParam

from vortex.domain.messages import Message, MessageRole
from vortex.domain.model_events import (
    ModelCompleted,
    ModelEvent,
    TextDelta,
    TokenUsage,
    ToolCallAvailable,
)
from vortex.domain.tools import ToolCall, ToolDefinition
from vortex.providers.errors import ModelError, ModelProtocolError


@dataclass(slots=True)
class _ToolCallBuffer:
    """聚合同一 index 的流式工具调用分片。"""

    identifier: str = ""
    name_parts: list[str] = field(default_factory=list)
    argument_parts: list[str] = field(default_factory=list)


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

    async def stream(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolDefinition] = (),
    ) -> AsyncIterator[ModelEvent]:
        """将 DeepSeek SSE 分片转换成 Vortex 模型事件。"""
        api_messages = [_to_api_message(message) for message in messages]
        api_tools = [_to_api_tool(tool) for tool in tools]
        finish_reason = "unknown"
        usage: TokenUsage | None = None
        tool_buffers: dict[int, _ToolCallBuffer] = {}

        try:
            if api_tools:
                stream = await self._client.chat.completions.create(
                    model=self.model_name,
                    messages=api_messages,
                    tools=api_tools,
                    tool_choice="auto",
                    stream=True,
                    stream_options={"include_usage": True},
                    extra_body={"thinking": {"type": "disabled"}},
                )
            else:
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
                        for tool_delta in choice.delta.tool_calls or ():
                            buffer = tool_buffers.setdefault(tool_delta.index, _ToolCallBuffer())
                            if tool_delta.id:
                                buffer.identifier = tool_delta.id
                            if tool_delta.function is not None:
                                if tool_delta.function.name:
                                    buffer.name_parts.append(tool_delta.function.name)
                                if tool_delta.function.arguments:
                                    buffer.argument_parts.append(tool_delta.function.arguments)
                        if choice.finish_reason is not None:
                            finish_reason = choice.finish_reason
            finally:
                await stream.close()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise _translate_error(exc) from exc

        for index in sorted(tool_buffers):
            yield ToolCallAvailable(_build_tool_call(index, tool_buffers[index]))
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
    if message.role is MessageRole.TOOL:
        assert message.tool_call_id is not None
        tool_message: ChatCompletionToolMessageParam = {
            "role": "tool",
            "content": message.content,
            "tool_call_id": message.tool_call_id,
        }
        return tool_message

    api_tool_calls: list[ChatCompletionMessageToolCallParam] = [
        {
            "id": call.id,
            "type": "function",
            "function": {
                "name": call.name,
                "arguments": json.dumps(call.arguments, ensure_ascii=False, separators=(",", ":")),
            },
        }
        for call in message.tool_calls
    ]
    assistant_message: ChatCompletionAssistantMessageParam = {
        "role": "assistant",
        "content": message.content or None,
    }
    if api_tool_calls:
        assistant_message["tool_calls"] = api_tool_calls
    return assistant_message


def _to_api_tool(tool: ToolDefinition) -> ChatCompletionToolParam:
    """把 Vortex 工具定义转换成 OpenAI-compatible Function Tool。"""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.input_schema,
        },
    }


def _build_tool_call(index: int, buffer: _ToolCallBuffer) -> ToolCall:
    """校验并完成一个流式工具调用。"""
    name = "".join(buffer.name_parts)
    arguments_text = "".join(buffer.argument_parts) or "{}"
    if not buffer.identifier or not name:
        raise ModelProtocolError(
            f"Incomplete tool call metadata at index {index}",
            user_message="DeepSeek returned an incomplete tool call. Please try again.",
            retryable=True,
        )
    try:
        parsed: object = json.loads(arguments_text)
    except json.JSONDecodeError as exc:
        raise ModelProtocolError(
            f"Invalid tool arguments JSON at index {index}",
            user_message="DeepSeek returned invalid tool arguments. Please try again.",
            retryable=True,
        ) from exc
    if not isinstance(parsed, dict) or any(not isinstance(key, str) for key in parsed):
        raise ModelProtocolError(
            f"Tool arguments at index {index} are not a JSON object",
            user_message="DeepSeek returned invalid tool arguments. Please try again.",
        )
    return ToolCall(
        id=buffer.identifier,
        name=name,
        arguments=cast(dict[str, object], parsed),
    )


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
