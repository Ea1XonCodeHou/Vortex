"""DeepSeek 适配器的协议级测试。"""

import json

import httpx
import pytest

from vortex.domain.messages import Message, MessageRole
from vortex.domain.model_events import ModelCompleted, TextDelta, ToolCallAvailable
from vortex.domain.tools import ToolCall, ToolDefinition, ToolRisk
from vortex.providers.deepseek import DeepSeekProvider
from vortex.providers.errors import ModelProtocolError


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


async def test_stream_assembles_native_tool_call_deltas_and_serializes_tool_history() -> None:
    captured_body: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_body.update(json.loads(request.content))
        stream_body = "\n".join(
            (
                'data: {"id":"chat-2","object":"chat.completion.chunk",'
                '"created":1,"model":"deepseek-v4-flash","choices":[{'
                '"index":0,"delta":{"role":"assistant","tool_calls":[{'
                '"index":0,"id":"call-2","type":"function","function":{'
                '"name":"read_","arguments":"{\\"pa"}}]},"finish_reason":null}]}',
                "",
                'data: {"id":"chat-2","object":"chat.completion.chunk",'
                '"created":1,"model":"deepseek-v4-flash","choices":[{'
                '"index":0,"delta":{"tool_calls":[{"index":0,"function":{'
                '"name":"file","arguments":"th\\":\\"README.md\\"}"}}]},'
                '"finish_reason":"tool_calls"}]}',
                "",
                'data: {"id":"chat-2","object":"chat.completion.chunk",'
                '"created":1,"model":"deepseek-v4-flash","choices":[],"usage":{'
                '"prompt_tokens":20,"completion_tokens":5,"total_tokens":25}}',
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

    previous_call = ToolCall(id="call-1", name="list_directory", arguments={"path": "."})
    messages = (
        Message(MessageRole.SYSTEM, "You are Vortex."),
        Message(MessageRole.USER, "Inspect the workspace"),
        Message(MessageRole.ASSISTANT, tool_calls=(previous_call,)),
        Message(MessageRole.TOOL, "README.md", tool_call_id="call-1"),
    )
    tools = (
        ToolDefinition(
            name="read_file",
            description="Read a workspace file.",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
            risk=ToolRisk.READ,
        ),
    )
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = DeepSeekProvider(api_key="test-key", http_client=http_client)

    events = [event async for event in provider.stream(messages, tools)]
    await provider.aclose()

    tool_event = next(event for event in events if isinstance(event, ToolCallAvailable))
    assert tool_event.call == ToolCall(
        id="call-2",
        name="read_file",
        arguments={"path": "README.md"},
    )
    assert captured_body["tool_choice"] == "auto"
    assert captured_body["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a workspace file.",
                "parameters": tools[0].input_schema,
            },
        }
    ]
    api_messages = captured_body["messages"]
    assert isinstance(api_messages, list)
    assert api_messages[-2] == {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call-1",
                "type": "function",
                "function": {
                    "name": "list_directory",
                    "arguments": '{"path":"."}',
                },
            }
        ],
    }
    assert api_messages[-1] == {
        "role": "tool",
        "content": "README.md",
        "tool_call_id": "call-1",
    }
    completed = next(event for event in events if isinstance(event, ModelCompleted))
    assert completed.finish_reason == "tool_calls"
    assert completed.usage is not None
    assert completed.usage.total_tokens == 25


async def test_invalid_streamed_tool_arguments_raise_safe_protocol_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        stream_body = "\n".join(
            (
                'data: {"id":"chat-3","object":"chat.completion.chunk",'
                '"created":1,"model":"deepseek-v4-flash","choices":[{'
                '"index":0,"delta":{"tool_calls":[{"index":0,"id":"call-3",'
                '"type":"function","function":{"name":"read_file","arguments":"{"}}]},'
                '"finish_reason":"tool_calls"}]}',
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

    provider = DeepSeekProvider(
        api_key="test-key",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(ModelProtocolError) as error:
        _ = [
            event
            async for event in provider.stream(
                (Message(MessageRole.USER, "Read a file"),),
                (
                    ToolDefinition(
                        name="read_file",
                        description="Read a file.",
                        input_schema={"type": "object", "properties": {}},
                        risk=ToolRisk.READ,
                    ),
                ),
            )
        ]
    await provider.aclose()

    assert error.value.user_message == "DeepSeek returned invalid tool arguments. Please try again."
