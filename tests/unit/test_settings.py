"""本地配置加载测试。"""

from pathlib import Path

import pytest

from vortex.config.settings import ConfigurationError, VortexSettings


def test_defaults_use_deepseek_v4_flash(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("VORTEX_MODEL", raising=False)

    settings = VortexSettings()

    assert settings.vortex_model == "deepseek-v4-flash"
    assert settings.deepseek_base_url == "https://api.deepseek.com"
    with pytest.raises(ConfigurationError, match="DEEPSEEK_API_KEY"):
        settings.require_api_key()


def test_dotenv_loads_secret_without_exposing_it(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("DEEPSEEK_API_KEY=test-secret\n", encoding="utf-8")

    settings = VortexSettings()

    assert settings.require_api_key() == "test-secret"
    assert "test-secret" not in repr(settings)
