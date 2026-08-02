"""CLI 入口测试。"""

from pytest import MonkeyPatch
from typer.testing import CliRunner

import vortex.cli.app as cli_module

runner = CliRunner()


def test_version_option() -> None:
    result = runner.invoke(cli_module.cli, ["--version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == "Vortex 0.0.2"


def test_help_option() -> None:
    result = runner.invoke(cli_module.cli, ["--help"])

    assert result.exit_code == 0
    assert "Vortex local Agent Runtime." in result.stdout


def test_no_arguments_launches_tui(monkeypatch: MonkeyPatch) -> None:
    launched = False

    def fake_run_tui() -> None:
        nonlocal launched
        launched = True

    monkeypatch.setattr(cli_module, "run_tui", fake_run_tui)

    result = runner.invoke(cli_module.cli)

    assert result.exit_code == 0
    assert launched is True
