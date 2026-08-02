"""Vortex 项目绑定配置的加载测试。"""

from pathlib import Path

import pytest

from vortex.config.paths import VORTEX_ENV_FILE, VORTEX_PROJECT_ROOT
from vortex.config.settings import ConfigurationError, VortexSettings, load_vortex_settings


def test_defaults_use_deepseek_v4_flash(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("VORTEX_MODEL", raising=False)

    settings = VortexSettings()

    assert settings.vortex_model == "deepseek-v4-flash"
    assert settings.deepseek_base_url == "https://api.deepseek.com"
    assert settings.max_agent_iterations == 24
    assert settings.max_agent_tool_calls == 64
    assert settings.tool_timeout_seconds == 15.0
    with pytest.raises(ConfigurationError, match="DEEPSEEK_API_KEY"):
        settings.require_api_key()


def test_private_project_config_is_independent_from_workspace_and_shell(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    private_config = tmp_path / "vortex.env"
    private_config.write_text(
        "DEEPSEEK_API_KEY=project-secret\nVORTEX_MODEL=project-model\n",
        encoding="utf-8",
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".env").write_text(
        "DEEPSEEK_API_KEY=workspace-secret\nVORTEX_MODEL=workspace-model\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(workspace)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "shell-secret")
    monkeypatch.setenv("VORTEX_MODEL", "shell-model")

    settings = load_vortex_settings(private_config)

    assert settings.require_api_key() == "project-secret"
    assert settings.vortex_model == "project-model"
    assert "project-secret" not in repr(settings)
    assert "workspace-secret" not in repr(settings)
    assert "shell-secret" not in repr(settings)


def test_default_private_config_path_is_bound_to_vortex_repository() -> None:
    repository_root = Path(__file__).resolve().parents[2]

    assert repository_root == VORTEX_PROJECT_ROOT
    assert repository_root / ".env" == VORTEX_ENV_FILE
