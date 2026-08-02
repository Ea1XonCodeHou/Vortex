"""欢迎页面的无头启动测试。"""

from pathlib import Path

import pytest
from textual.containers import Horizontal
from textual.content import Content
from textual.widgets import Input, Markdown, Static

from tests.support.fake_provider import BlockingProvider, FakeProvider
from tests.support.fake_tool import FakeTool
from vortex.config.settings import VortexSettings
from vortex.domain.model_events import ModelCompleted, ToolCallAvailable
from vortex.domain.tools import ToolCall, ToolResult
from vortex.providers.errors import ModelError
from vortex.tools.registry import ToolRegistry
from vortex.tui.app import VortexApp
from vortex.tui.screens.approval import ToolApprovalScreen
from vortex.tui.screens.welcome import WelcomeScreen
from vortex.tui.widgets.chat_message import ChatMessage
from vortex.tui.widgets.tool_call import ToolCallView


async def test_welcome_screen_starts(tmp_path: Path) -> None:
    workspace = tmp_path
    app = VortexApp(
        workspace=workspace,
        provider=FakeProvider([["Hello"]]),
    )

    async with app.run_test(size=(120, 32)) as pilot:
        await pilot.pause()

        panel = app.screen.query_one("#welcome-panel", Horizontal)
        prompt = app.screen.query_one("#prompt", Input)
        workspace_path = app.screen.query_one("#workspace-path", Static)

        assert panel.border_title == " Vortex v0.2.0 "
        assert prompt.has_focus
        assert str(workspace) in str(workspace_path.content)


async def test_prompt_streams_model_response(tmp_path: Path) -> None:
    provider = FakeProvider([["Hello", " from", " DeepSeek"]])
    app = VortexApp(workspace=tmp_path, provider=provider)

    async with app.run_test(size=(120, 32)) as pilot:
        prompt = app.screen.query_one("#prompt", Input)

        placeholder_lines = [prompt.render_line(line).text for line in range(prompt.size.height)]
        assert any("Describe a task for Vortex..." in line for line in placeholder_lines)

        await pilot.press(*"inspect this project")
        await pilot.pause()

        assert prompt.value == "inspect this project"
        rendered_lines = [prompt.render_line(line).text for line in range(prompt.size.height)]
        assert any("inspect this project" in line for line in rendered_lines)

        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()

        messages = list(app.screen.query(ChatMessage))
        assert [message.kind for message in messages] == ["user", "assistant"]
        assert messages[0].body == "inspect this project"
        assert messages[1].body == "Hello from DeepSeek"
        assert messages[1].state == "completed"
        assert len(messages[0].query(Markdown)) == 0
        assert messages[1].query_one(Markdown).source == "Hello from DeepSeek"
        assert prompt.disabled is False
        assert prompt.has_focus
        assert len(provider.requests) == 1


async def test_missing_api_key_is_reported_without_crashing(
    tmp_path: Path,
) -> None:
    app = VortexApp(workspace=tmp_path, settings=VortexSettings())

    async with app.run_test(size=(120, 32)) as pilot:
        await pilot.press(*"hello")
        await pilot.press("enter")
        await pilot.pause()

        messages = list(app.screen.query(ChatMessage))
        assert messages[-1].kind == "error"
        assert "DEEPSEEK_API_KEY" in messages[-1].body


async def test_active_stream_can_be_cancelled(tmp_path: Path) -> None:
    provider = BlockingProvider()
    app = VortexApp(workspace=tmp_path, provider=provider)

    async with app.run_test(size=(120, 32)) as pilot:
        prompt = app.screen.query_one("#prompt", Input)
        await pilot.press(*"long response")
        await pilot.press("enter")
        await provider.started.wait()

        assert prompt.disabled is True
        await pilot.press("ctrl+c")
        await pilot.pause()

        messages = list(app.screen.query(ChatMessage))
        assert messages[-1].state == "cancelled"
        assert messages[-1].body == "partial"
        assert prompt.disabled is False
        assert prompt.has_focus


async def test_provider_error_is_safe_and_input_recovers(tmp_path: Path) -> None:
    error = ModelError("raw provider details", user_message="Safe provider error")
    provider = FakeProvider([], error=error)
    app = VortexApp(workspace=tmp_path, provider=provider)

    async with app.run_test(size=(120, 32)) as pilot:
        prompt = app.screen.query_one("#prompt", Input)
        await pilot.press(*"hello")
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()

        messages = list(app.screen.query(ChatMessage))
        assert messages[-1].state == "failed"
        assert messages[-1].body == ""
        assert messages[-1].status_message == "Safe provider error"
        assert "raw provider details" not in messages[-1].status_message
        assert prompt.disabled is False


async def test_streaming_markdown_renders_gfm_across_chunk_boundaries(tmp_path: Path) -> None:
    fragments = [
        "### Head",
        "ing\n\nA **bo",
        "ld** statement.\n\n- first\n- second\n\n```python\n",
        "print('ok')\n```\n\n| Product | Type |\n",
        "|---|---|\n| Vortex | Agent |",
    ]
    provider = FakeProvider([fragments])
    app = VortexApp(workspace=tmp_path, provider=provider)

    async with app.run_test(size=(140, 50)) as pilot:
        await pilot.press(*"render markdown")
        await pilot.press("enter")
        await app.workers.wait_for_complete()
        await pilot.pause()

        assistant = list(app.screen.query(ChatMessage))[-1]
        markdown = assistant.query_one(Markdown)
        heading = markdown.query_one("MarkdownH3")
        paragraph = markdown.query_one("MarkdownParagraph")
        paragraph_content = paragraph.render()

        assert markdown.source == "".join(fragments)
        assert len(markdown.query("MarkdownH3")) == 1
        assert len(markdown.query("MarkdownBulletList")) == 1
        assert len(markdown.query("MarkdownFence")) == 1
        assert len(markdown.query("MarkdownTable")) == 1
        assert heading.render_line(0).text == "Heading"
        assert isinstance(paragraph_content, Content)
        assert paragraph_content.plain == "A bold statement."
        assert any(span.style == ".strong" for span in paragraph_content.spans)


async def test_tool_call_and_observation_are_rendered_before_final_answer(
    tmp_path: Path,
) -> None:
    call = ToolCall(id="call-1", name="inspect", arguments={"path": "README.md"})
    provider = FakeProvider(
        [
            [ToolCallAvailable(call), ModelCompleted(finish_reason="tool_calls")],
            ["The workspace contains a README.", ModelCompleted(finish_reason="stop")],
        ]
    )
    tool = FakeTool(ToolResult.success("# Vortex"))
    app = VortexApp(
        workspace=tmp_path,
        provider=provider,
        registry=ToolRegistry((tool,)),
    )

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.press(*"inspect the workspace")
        await pilot.press("enter")
        await pilot.pause()

        assert isinstance(app.screen, ToolApprovalScreen)
        await pilot.press("s")
        await app.workers.wait_for_complete()
        await pilot.pause()

        tool_view = app.screen.query_one(ToolCallView)
        messages = list(app.screen.query(ChatMessage))

        assert tool_view.call == call
        assert tool_view.state == "succeeded"
        assert tool_view.result == ToolResult.success("# Vortex")
        assert [message.kind for message in messages] == ["user", "assistant"]
        assert messages[-1].body == "The workspace contains a README."
        assert messages[-1].state == "completed"
        assert len(provider.requests) == 2


async def test_denied_tool_is_not_executed_and_conversation_recovers(
    tmp_path: Path,
) -> None:
    call = ToolCall(id="call-1", name="inspect", arguments={"path": "README.md"})
    provider = FakeProvider(
        [
            [ToolCallAvailable(call), ModelCompleted(finish_reason="tool_calls")],
            ["I could not inspect the file.", ModelCompleted(finish_reason="stop")],
        ]
    )
    tool = FakeTool(ToolResult.success("private contents"))
    app = VortexApp(
        workspace=tmp_path,
        provider=provider,
        registry=ToolRegistry((tool,)),
    )

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.press(*"inspect the workspace")
        await pilot.press("enter")
        await pilot.pause()

        assert isinstance(app.screen, ToolApprovalScreen)
        await pilot.press("d")
        await app.workers.wait_for_complete()
        await pilot.pause()

        tool_view = app.screen.query_one(ToolCallView)
        messages = list(app.screen.query(ChatMessage))
        prompt = app.screen.query_one("#prompt", Input)

        assert tool.calls == []
        assert tool_view.state == "failed"
        assert tool_view.result is not None
        assert tool_view.result.error_code is not None
        assert tool_view.result.error_code.value == "permission_denied"
        assert messages[-1].body == "I could not inspect the file."
        assert prompt.disabled is False
        assert prompt.has_focus


async def test_selected_assistant_text_can_be_copied_and_pasted_into_prompt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    provider = FakeProvider([["Copy this answer"]])
    app = VortexApp(workspace=tmp_path, provider=provider)
    selected: list[str | None] = ["Copy this answer"]

    monkeypatch.setattr(
        WelcomeScreen,
        "get_selected_text",
        lambda self: selected[0],
    )

    async with app.run_test(size=(120, 32)) as pilot:
        await pilot.press("ctrl+c")
        await pilot.pause()
        assert app.clipboard == "Copy this answer"

        selected[0] = None
        await pilot.press("ctrl+v")
        await pilot.pause()

        prompt = app.screen.query_one("#prompt", Input)
        assert prompt.value == "Copy this answer"
