"""Vortex 欢迎与对话页面。"""

import asyncio
import logging
from pathlib import Path

from textual import events, on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Input, Static
from textual.worker import Worker

from vortex import __version__
from vortex.domain.model_events import TokenUsage
from vortex.domain.permissions import ApprovalDecision, ToolApprovalRequest
from vortex.domain.run_events import (
    AssistantTextDelta,
    RunFinished,
    RunStatus,
    TerminationReason,
    ToolApprovalRequested,
    ToolApprovalResolved,
    ToolCallFinished,
    ToolCallStarted,
)
from vortex.permissions.session import SessionApprovalManager
from vortex.providers.errors import ModelError
from vortex.runtime.agent import AgentBusyError, AgentRuntime
from vortex.tui.screens.approval import ToolApprovalScreen
from vortex.tui.widgets.chat_message import ChatMessage, MarkdownStreamWriter
from vortex.tui.widgets.tool_call import ToolCallView

log = logging.getLogger(__name__)

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
    BINDINGS = [
        Binding("ctrl+c", "copy_or_cancel", "Copy or cancel", show=False, priority=True),
        Binding(
            "super+c,ctrl+shift+c",
            "copy_selection",
            "Copy selection",
            show=False,
            priority=True,
        ),
    ]

    def __init__(
        self,
        workspace: Path,
        *,
        agent_runtime: AgentRuntime | None,
        approval_manager: SessionApprovalManager,
        model_name: str,
        startup_error: str | None = None,
    ) -> None:
        super().__init__()
        self.workspace = workspace
        self.agent_runtime = agent_runtime
        self.approval_manager = approval_manager
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
                    "Ctrl+C copies a selection or cancels a response · Ctrl+Q leaves.",
                    classes="section-copy",
                )
                yield Static("", classes="section-rule")
                yield Static("Current milestone", classes="section-title")
                yield Static(
                    "Single-agent workspace inspection is ready.\n"
                    "Runs and conversation history remain in memory.",
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
        self.approval_manager.set_prompt(self._request_tool_approval)
        self.call_after_refresh(self._focus_prompt)

    def on_unmount(self) -> None:
        """页面离开后断开交互回调，避免悬挂 UI 引用。"""
        self.approval_manager.set_prompt(None)

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

        if self.agent_runtime is None:
            await transcript.mount(
                ChatMessage(
                    "error",
                    self.startup_error or "The model provider is not available.",
                    state="failed",
                )
            )
            transcript.scroll_end(animate=False)
            return

        transcript.anchor()
        event.input.disabled = True
        self._set_status(f"Running · {self.model_name} · Ctrl+C to cancel")
        self._active_worker = self._run_agent(value)

    @work(exclusive=True, group="chat")
    async def _run_agent(self, user_text: str) -> None:
        """消费 Agent Runtime 事件并按真实顺序渲染文本与工具调用。"""
        if self.agent_runtime is None:
            return

        transcript = self.query_one("#transcript", VerticalScroll)
        message: ChatMessage | None = None
        markdown_stream: MarkdownStreamWriter | None = None
        tool_views: dict[str, ToolCallView] = {}
        terminal_event: RunFinished | None = None

        async def finish_text_segment() -> None:
            nonlocal message, markdown_stream
            if markdown_stream is not None:
                await markdown_stream.stop()
            if message is not None:
                message.set_state("completed")
            message = None
            markdown_stream = None

        try:
            async for event in self.agent_runtime.run(user_text):
                if isinstance(event, AssistantTextDelta):
                    if message is None:
                        message = ChatMessage("assistant", state="streaming")
                        await transcript.mount(message)
                        self._active_message = message
                        markdown_stream = message.open_markdown_stream()
                    if markdown_stream is not None:
                        message.record_text(event.text)
                        await markdown_stream.write(event.text)
                elif isinstance(event, ToolCallStarted):
                    await finish_text_segment()
                    view = ToolCallView(event.call)
                    tool_views[event.call.id] = view
                    await transcript.mount(view)
                elif isinstance(event, ToolApprovalRequested):
                    self._set_status(f"Waiting for permission · {event.request.call.name}")
                elif isinstance(event, ToolApprovalResolved):
                    decision = event.outcome.decision.value.replace("_", " ")
                    source = "cached" if event.outcome.cached else "user"
                    self._set_status(f"Running · {event.request.call.name} · {decision} ({source})")
                elif isinstance(event, ToolCallFinished):
                    existing_view = tool_views.get(event.call.id)
                    if existing_view is not None:
                        existing_view.finish(event.result, event.elapsed_ms)
                elif isinstance(event, RunFinished):
                    terminal_event = event

            await finish_text_segment()
            if terminal_event is None:
                raise RuntimeError("Agent Runtime ended without a terminal event")
            if terminal_event.status is RunStatus.SUCCEEDED:
                self._set_status(self._completed_status(terminal_event))
            elif terminal_event.status is RunStatus.LIMIT_REACHED:
                limit_message = (
                    f"Agent could not finalize after {terminal_event.iterations} steps and "
                    f"{terminal_event.tool_calls} executed tools "
                    f"({terminal_event.reason.value}). Try a narrower task."
                )
                await transcript.mount(ChatMessage("error", limit_message, state="failed"))
                self._set_status(limit_message, error=True)
        except asyncio.CancelledError:
            if markdown_stream is not None:
                await markdown_stream.stop()
                markdown_stream = None
            if message is not None:
                message.set_state("cancelled")
            else:
                cancelled = ChatMessage("assistant", state="cancelled")
                await transcript.mount(cancelled)
            self._set_status(f"Cancelled · {self.model_name}")
            raise
        except (ModelError, AgentBusyError) as exc:
            if markdown_stream is not None:
                await markdown_stream.stop()
                markdown_stream = None
            user_message = exc.user_message if isinstance(exc, ModelError) else str(exc)
            if message is None:
                message = ChatMessage("assistant", state="failed")
                await transcript.mount(message)
            message.set_error(user_message)
            self._set_status(user_message, error=True)
        except Exception:
            log.exception("Unexpected TUI agent run failure")
            if markdown_stream is not None:
                await markdown_stream.stop()
                markdown_stream = None
            if message is None:
                message = ChatMessage("assistant", state="failed")
                await transcript.mount(message)
            message.set_error("The response failed unexpectedly. Please try again.")
            self._set_status("The response failed unexpectedly. Please try again.", error=True)
        finally:
            if markdown_stream is not None:
                await markdown_stream.stop()
            prompt = self.query_one("#prompt", Input)
            prompt.disabled = False
            prompt.focus()
            self._active_worker = None
            self._active_message = None

    def action_cancel_response(self) -> None:
        """取消当前生成，保留已显示文本但不提交到对话历史。"""
        if self._active_worker is not None and not self._active_worker.is_finished:
            self._active_worker.cancel()

    async def _request_tool_approval(
        self,
        request: ToolApprovalRequest,
    ) -> ApprovalDecision:
        """在 Agent Worker 中等待审批弹窗返回决定。"""
        return await self.app.push_screen_wait(ToolApprovalScreen(request))

    def action_copy_selection(self) -> None:
        """优先复制对话区选区，其次复制输入框选区。"""
        selected = self.get_selected_text()
        prompt = self.query_one("#prompt", Input)
        text = selected or prompt.selected_text
        if text:
            self.app.copy_to_clipboard(text)
            self._set_status("Copied selection to clipboard")

    def action_copy_or_cancel(self) -> None:
        """有选区时复制，否则仅在生成期间执行取消。"""
        selected = self.get_selected_text()
        prompt = self.query_one("#prompt", Input)
        if selected or prompt.selected_text:
            self.action_copy_selection()
            return
        self.action_cancel_response()

    def _completed_status(self, event: RunFinished) -> str:
        usage: TokenUsage | None = event.usage
        progress = f"{event.iterations} steps / {event.tool_calls} tools"
        if event.reason is TerminationReason.BUDGET_FINALIZED:
            progress += " / finalized at budget"
        if usage is None:
            return f"Ready · {self.model_name} · {progress}"
        return (
            f"Ready · {self.model_name} · {progress} · "
            f"{usage.input_tokens} input / {usage.output_tokens} output tokens"
        )

    def _set_status(self, message: str, *, error: bool = False) -> None:
        status = self.query_one("#interface-status", Static)
        color = "#fb7185" if error else "#94a3b8"
        status.update(f"[{color}]│  {message}[/]")
