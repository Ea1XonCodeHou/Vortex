"""Vortex 欢迎与对话页面。"""

import asyncio
from pathlib import Path

from textual import events, on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Input, Static
from textual.worker import Worker

from vortex import __version__
from vortex.domain.model_events import ModelCompleted, TextDelta, TokenUsage
from vortex.providers.errors import ModelError
from vortex.runtime.chat import ChatBusyError, ChatService
from vortex.tui.widgets.chat_message import ChatMessage

VORTEX_LOGO = """\
██╗       ██╗
╚██╗     ██╔╝
 ╚██╗   ██╔╝
  ╚██╗ ██╔╝
   ╚████╔╝
    ╚═══╝"""


class WelcomeScreen(Screen[None]):
    """启动后显示的产品欢迎页。"""

    AUTO_FOCUS = "#prompt"
    BINDINGS = [Binding("ctrl+c", "cancel_response", "Cancel response", show=False)]

    def __init__(
        self,
        workspace: Path,
        *,
        chat_service: ChatService | None,
        model_name: str,
        startup_error: str | None = None,
    ) -> None:
        super().__init__()
        self.workspace = workspace
        self.chat_service = chat_service
        self.model_name = model_name
        self.startup_error = startup_error
        self._active_worker: Worker[None] | None = None
        self._active_message: ChatMessage | None = None

    def compose(self) -> ComposeResult:
        yield Static("➜  ~  Vortex", id="product-line")

        with Horizontal(id="welcome-panel"):
            with Vertical(id="brand-pane"):
                yield Static("Welcome back!", id="welcome-title")
                with Center(id="logo-row"):
                    yield Static(VORTEX_LOGO, id="vortex-logo")
                yield Static("Local Agent Runtime", id="product-description")
                yield Static(str(self.workspace), id="workspace-path")

            with Vertical(id="info-pane"):
                yield Static("Tips for getting started", classes="section-title")
                yield Static(
                    "Launch Vortex inside the project you want to work on.\n"
                    "Press Ctrl+C to cancel a response · Ctrl+Q to leave.",
                    classes="section-copy",
                )
                yield Static("", classes="section-rule")
                yield Static("Current milestone", classes="section-title")
                yield Static(
                    "Streaming chat with DeepSeek V4 Flash is ready.\n"
                    "Conversation history remains local to this process.",
                    classes="section-copy",
                )

        yield Static("", id="interface-status")
        yield VerticalScroll(id="transcript")

        with Horizontal(id="prompt-row"):
            yield Static("❯", id="prompt-symbol")
            yield Input(
                placeholder="Describe a task for Vortex...",
                id="prompt",
            )

        yield Static("Vortex  ·  Local workspace  ·  Interface ready", id="status-bar")

    def on_mount(self) -> None:
        """设置边框标题、连接状态并聚焦输入框。"""
        panel = self.query_one("#welcome-panel", Horizontal)
        panel.border_title = f" Vortex v{__version__} "
        if self.startup_error is None:
            self._set_status(f"Ready · {self.model_name} · In-memory conversation")
        else:
            self._set_status(self.startup_error, error=True)
        self.call_after_refresh(self._focus_prompt)

    def _focus_prompt(self) -> None:
        """避免页面挂载过程覆盖输入框焦点。"""
        self.query_one("#prompt", Input).focus()

    def on_resize(self, event: events.Resize) -> None:
        """窄终端隐藏辅助信息，保证 Logo 和输入区域仍然可用。"""
        if event.size.width < 88:
            self.add_class("compact")
        else:
            self.remove_class("compact")

    @on(Input.Submitted, "#prompt")
    async def handle_prompt_submitted(self, event: Input.Submitted) -> None:
        """提交用户消息并启动后台流式生成。"""
        value = event.value.strip()
        if not value:
            return
        if self._active_worker is not None and not self._active_worker.is_finished:
            return

        event.input.clear()
        transcript = self.query_one("#transcript", VerticalScroll)
        await transcript.mount(ChatMessage("user", value))

        if self.chat_service is None:
            await transcript.mount(
                ChatMessage(
                    "error",
                    self.startup_error or "The model provider is not available.",
                    state="failed",
                )
            )
            transcript.scroll_end(animate=False)
            return

        assistant_message = ChatMessage("assistant", state="streaming")
        await transcript.mount(assistant_message)
        transcript.anchor()
        event.input.disabled = True
        self._active_message = assistant_message
        self._set_status(f"Generating · {self.model_name} · Ctrl+C to cancel")
        self._active_worker = self._stream_response(value, assistant_message)

    @work(exclusive=True, group="chat")
    async def _stream_response(self, user_text: str, message: ChatMessage) -> None:
        """在 Textual Worker 中消费异步模型流，避免阻塞界面事件循环。"""
        if self.chat_service is None:
            return

        usage: TokenUsage | None = None
        markdown_stream = message.open_markdown_stream()

        try:
            try:
                async for event in self.chat_service.stream_reply(user_text):
                    if isinstance(event, TextDelta):
                        message.record_text(event.text)
                        await markdown_stream.write(event.text)
                    elif isinstance(event, ModelCompleted):
                        usage = event.usage
            finally:
                # stop 会刷出 MarkdownStream 尚未合并的最后一批分片
                await markdown_stream.stop()

            message.set_state("completed")
            self._set_status(self._completed_status(usage))
        except asyncio.CancelledError:
            message.set_state("cancelled")
            self._set_status(f"Cancelled · {self.model_name}")
            raise
        except (ModelError, ChatBusyError) as exc:
            user_message = exc.user_message if isinstance(exc, ModelError) else str(exc)
            message.set_error(user_message)
            self._set_status(user_message, error=True)
        except Exception:
            message.set_error("The response failed unexpectedly. Please try again.")
            self._set_status("The response failed unexpectedly. Please try again.", error=True)
        finally:
            prompt = self.query_one("#prompt", Input)
            prompt.disabled = False
            prompt.focus()
            self._active_worker = None
            self._active_message = None

    def action_cancel_response(self) -> None:
        """取消当前生成，保留已显示文本但不提交到对话历史。"""
        if self._active_worker is not None and not self._active_worker.is_finished:
            self._active_worker.cancel()

    def _completed_status(self, usage: TokenUsage | None) -> str:
        if usage is None:
            return f"Ready · {self.model_name} · In-memory conversation"
        return (
            f"Ready · {self.model_name} · "
            f"{usage.input_tokens} input / {usage.output_tokens} output tokens"
        )

    def _set_status(self, message: str, *, error: bool = False) -> None:
        status = self.query_one("#interface-status", Static)
        color = "#fb7185" if error else "#94a3b8"
        status.update(f"[{color}]│  {message}[/]")
