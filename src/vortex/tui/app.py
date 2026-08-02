"""Textual 应用入口。"""

from pathlib import Path

from textual.app import App

from vortex import __version__
from vortex.config.settings import ConfigurationError, VortexSettings
from vortex.providers.base import ModelProvider
from vortex.providers.deepseek import DeepSeekProvider
from vortex.runtime.chat import ChatService
from vortex.tui.screens.welcome import WelcomeScreen


class VortexApp(App[None]):
    """Vortex 的顶层 TUI 应用。"""

    CSS_PATH = "styles/vortex.tcss"
    TITLE = "Vortex"
    SUB_TITLE = f"v{__version__}"
    BINDINGS = [
        ("ctrl+q", "quit", "Quit"),
    ]

    def __init__(
        self,
        workspace: Path | None = None,
        *,
        provider: ModelProvider | None = None,
        settings: VortexSettings | None = None,
    ) -> None:
        super().__init__()
        self.workspace = (workspace or Path.cwd()).resolve()
        self.settings = settings or VortexSettings()
        self.chat_service: ChatService | None = None
        self.startup_error: str | None = None

        try:
            active_provider = provider or DeepSeekProvider(
                api_key=self.settings.require_api_key(),
                model=self.settings.vortex_model,
                base_url=self.settings.deepseek_base_url,
                timeout_seconds=self.settings.request_timeout_seconds,
            )
            self.chat_service = ChatService(
                active_provider,
                system_prompt=self.settings.system_prompt(),
            )
        except ConfigurationError as exc:
            self.startup_error = str(exc)

    def on_mount(self) -> None:
        """应用启动后挂载对话页。"""
        self.push_screen(
            WelcomeScreen(
                self.workspace,
                chat_service=self.chat_service,
                model_name=(
                    self.chat_service.model_name
                    if self.chat_service is not None
                    else self.settings.vortex_model
                ),
                startup_error=self.startup_error,
            )
        )

    async def on_unmount(self) -> None:
        if self.chat_service is not None:
            await self.chat_service.aclose()


def run_tui(workspace: Path | None = None) -> None:
    """启动 Vortex 全屏终端界面。"""
    VortexApp(workspace=workspace).run()
