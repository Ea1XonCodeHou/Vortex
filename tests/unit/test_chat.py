"""临时对话运行时测试。"""

import asyncio

import pytest

from tests.support.fake_provider import BlockingProvider, FakeProvider
from vortex.domain.messages import Message, MessageRole
from vortex.domain.model_events import ModelCompleted
from vortex.providers.errors import ModelError
from vortex.runtime.chat import ChatService


async def test_successful_round_is_committed_and_used_by_next_round() -> None:
    provider = FakeProvider([["First answer"], ["Second answer"]])
    chat = ChatService(provider, system_prompt="You are Vortex.")

    first_events = [event async for event in chat.stream_reply("First question")]
    second_events = [event async for event in chat.stream_reply("Follow up")]

    assert any(isinstance(event, ModelCompleted) for event in first_events)
    assert any(isinstance(event, ModelCompleted) for event in second_events)
    assert [(message.role, message.content) for message in chat.messages] == [
        (MessageRole.SYSTEM, "You are Vortex."),
        (MessageRole.USER, "First question"),
        (MessageRole.ASSISTANT, "First answer"),
        (MessageRole.USER, "Follow up"),
        (MessageRole.ASSISTANT, "Second answer"),
    ]
    assert provider.requests[1] == chat.messages[:4]


async def test_failed_round_does_not_pollute_conversation_history() -> None:
    error = ModelError("failure", user_message="Safe failure")
    provider = FakeProvider([], error=error)
    chat = ChatService(provider, system_prompt="You are Vortex.")

    with pytest.raises(ModelError, match="failure"):
        _ = [event async for event in chat.stream_reply("Will fail")]

    assert chat.messages == (Message(MessageRole.SYSTEM, "You are Vortex."),)


async def test_cancelled_round_does_not_pollute_conversation_history() -> None:
    provider = BlockingProvider()
    chat = ChatService(provider, system_prompt="You are Vortex.")

    async def consume() -> None:
        _ = [event async for event in chat.stream_reply("Cancel me")]

    task = asyncio.create_task(consume())
    await provider.started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert chat.messages == (Message(MessageRole.SYSTEM, "You are Vortex."),)
