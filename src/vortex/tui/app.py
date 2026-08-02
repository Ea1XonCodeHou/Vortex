"""Textual 应用入口。"""

import asyncio
import logging
import sys
from pathlib import Path

from textual.app import App

from vortex import __version__
from vortex.config.settings import ConfigurationError, VortexSettings, load_vortex_settings
from vortex.permissions.session import SessionApprovalManager
from vortex.providers.base import ModelProvider
from vortex.providers.deepseek import DeepSeekProvider
from vortex.runtime.agent import AgentRuntime
from vortex.tools.builtin import build_workspace_registry
from vortex.tools.registry import ToolRegistry
from vortex.tui.screens.welcome import WelcomeScreen

log = logging.getLogger(__name__)


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
        registry: ToolRegistry | None = None,
        settings: VortexSettings | None = None,
    ) -> None:
        super().__init__()
        self.workspace = (workspace or Path.cwd()).resolve()
        if settings is not None:
            self.settings = settings
        elif provider is None:
            self.settings = load_vortex_settings()
        else:
            # 注入 Provider 的测试和嵌入场景不需要接触真实项目凭证。
            self.settings = VortexSettings()
        self.agent_runtime: AgentRuntime | None = None
        self.approval_manager = SessionApprovalManager()
        self.startup_error: str | None = None

        try:
            active_provider = provider or DeepSeekProvider(
                api_key=self.settings.require_api_key(),
                model=self.settings.vortex_model,
                base_url=self.settings.deepseek_base_url,
                timeout_seconds=self.settings.request_timeout_seconds,
            )
            active_registry = registry or build_workspace_registry(self.workspace)
            self.agent_runtime = AgentRuntime(
                active_provider,
                active_registry,
                self.approval_manager,
                system_prompt=self.settings.system_prompt(),
                max_iterations=self.settings.max_agent_iterations,
                max_tool_calls=self.settings.max_agent_tool_calls,
                tool_timeout_seconds=self.settings.tool_timeout_seconds,
            )
        except ConfigurationError as exc:
            self.startup_error = str(exc)

    def on_mount(self) -> None:
        """应用启动后挂载对话页。"""
        self.push_screen(
            WelcomeScreen(
                self.workspace,
                agent_runtime=self.agent_runtime,
                approval_manager=self.approval_manager,
                model_name=(
                    self.agent_runtime.model_name
                    if self.agent_runtime is not None
                    else self.settings.vortex_model
                ),
                startup_error=self.startup_error,
            )
        )

    async def on_unmount(self) -> None:
        if self.agent_runtime is not None:
            await self.agent_runtime.aclose()

    def copy_to_clipboard(self, text: str) -> None:
        """使用 Textual OSC 52，并在 macOS 上补充原生剪贴板写入。"""
        super().copy_to_clipboard(text)
        if sys.platform == "darwin" and not self.is_headless:
            self.run_worker(_copy_with_pbcopy(text), name="copy-to-macos-clipboard")


def run_tui(workspace: Path | None = None) -> None:
    """启动 Vortex 全屏终端界面。"""
    VortexApp(workspace=workspace).run()


async def _copy_with_pbcopy(text: str) -> None:
    """通过固定系统程序兼容不支持 OSC 52 的 macOS Terminal。"""
    try:
        process = await asyncio.create_subprocess_exec(
            "/usr/bin/pbcopy",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError:
        log.warning("macOS clipboard fallback is unavailable", exc_info=True)
        return

    try:
        await asyncio.wait_for(process.communicate(text.encode("utf-8")), timeout=2.0)
    except TimeoutError:
        process.kill()
        await process.wait()
        log.warning("macOS clipboard command timed out")
        return
    if process.returncode != 0:
        log.warning("macOS clipboard command exited with code %s", process.returncode)
