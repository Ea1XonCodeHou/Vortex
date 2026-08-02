"""DeepSeek 适配器的协议级测试。"""

import json

import httpx

from vortex.domain.messages import Message, MessageRole
from vortex.domain.model_events import ModelCompleted, TextDelta
from vortex.providers.deepseek import DeepSeekProvider


async def test_stream_request_disables_thinking_and_parses_usage() -> None:
    captured_body: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_body.update(json.loads(request.content))
        stream_body = "\n".join(
            (
                ": keep-alive",
                "",
                'data: {"id":"chat-1","object":"chat.completion.chunk",'
                '"created":1,"model":"deepseek-v4-flash","choices":[{'
                '"index":0,"delta":{"role":"assistant","content":"Hello"},'
                '"finish_reason":null}]}',
                "",
                'data: {"id":"chat-1","object":"chat.completion.chunk",'
                '"created":1,"model":"deepseek-v4-flash","choices":[{'
                '"index":0,"delta":{"content":" Vortex"},"finish_reason":"stop"}]}',
                "",
                'data: {"id":"chat-1","object":"chat.completion.chunk",'
                '"created":1,"model":"deepseek-v4-flash","choices":[],"usage":{'
                '"prompt_tokens":8,"completion_tokens":2,"total_tokens":10}}',
                "",
                "data: [DONE]",
                "",
            )
        )
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=stream_body,
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = DeepSeekProvider(api_key="test-key", http_client=http_client)
    messages = (
        Message(MessageRole.SYSTEM, "You are Vortex."),
        Message(MessageRole.USER, "Hello"),
    )

    events = [event async for event in provider.stream(messages)]
    await provider.aclose()

    assert captured_body["model"] == "deepseek-v4-flash"
    assert captured_body["stream"] is True
    assert captured_body["stream_options"] == {"include_usage": True}
    assert captured_body["thinking"] == {"type": "disabled"}
    assert captured_body["messages"] == [
        {"role": "system", "content": "You are Vortex."},
        {"role": "user", "content": "Hello"},
    ]
    assert [event.text for event in events if isinstance(event, TextDelta)] == [
        "Hello",
        " Vortex",
    ]
    completed = next(event for event in events if isinstance(event, ModelCompleted))
    assert completed.finish_reason == "stop"
    assert completed.usage is not None
    assert completed.usage.total_tokens == 10
