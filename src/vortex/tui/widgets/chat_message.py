"""对话消息展示组件。"""

from typing import Literal, Protocol

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Markdown, Static

MessageKind = Literal["user", "assistant", "error"]
MessageState = Literal["streaming", "completed", "cancelled", "failed"]


class MarkdownStreamWriter(Protocol):
    """Textual MarkdownStream 在 Vortex 中使用的最小协议。"""

    async def write(self, markdown_fragment: str) -> None: ...

    async def stop(self) -> None: ...


class ChatMessage(Vertical):
    """渲染一条用户消息、Markdown 模型回复或运行错误。"""

    def __init__(
        self,
        kind: MessageKind,
        body: str = "",
        *,
        state: MessageState = "completed",
    ) -> None:
        super().__init__(classes=f"chat-message {kind}-message")
        self.kind = kind
        self.body = body
        self.state = state
        self.status_message = ""

    def compose(self) -> ComposeResult:
        label = {
            "user": ("You", "bold #67e8f9"),
            "assistant": ("Vortex", "bold #a78bfa"),
            "error": ("Error", "bold #fb7185"),
        }[self.kind]
        yield Static(Text(label[0], style=label[1]), classes="message-label")

        if self.kind == "assistant":
            yield Markdown(self.body, classes="message-markdown")
            waiting = (
                Text("Waiting for DeepSeek...", style="italic #94a3b8")
                if self.state == "streaming" and not self.body
                else Text()
            )
            yield Static(waiting, classes="message-state")
        else:
            yield Static(Text(self.body), classes="message-plain")

    def open_markdown_stream(self) -> MarkdownStreamWriter:
        """为模型响应创建 Textual 原生增量 Markdown 流。"""
        if self.kind != "assistant":
            raise RuntimeError("Only assistant messages can stream Markdown")
        return Markdown.get_stream(self.query_one(Markdown))

    def record_text(self, text: str) -> None:
        """保存模型原始输出，供上下文提交与后续持久化使用。"""
        self.body += text
        state_widget = self.query_one(".message-state", Static)
        state_widget.update(Text())
        state_widget.display = False

    def set_state(self, state: MessageState) -> None:
        self.state = state
        state_widget = self.query_one(".message-state", Static)

        if state == "cancelled":
            self.status_message = "Response cancelled"
            state_widget.update(Text(self.status_message, style="italic #94a3b8"))
            state_widget.display = True
        elif state == "completed":
            self.status_message = ""
            state_widget.update(Text())
            state_widget.display = False

    def set_error(self, message: str) -> None:
        """保留已经生成的 Markdown，并追加纯文本错误状态。"""
        self.state = "failed"
        self.status_message = message
        state_widget = self.query_one(".message-state", Static)
        state_widget.update(Text(message, style="#fb7185"))
        state_widget.display = True
