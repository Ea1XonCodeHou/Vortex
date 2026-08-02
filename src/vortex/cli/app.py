"""Vortex CLI 命令定义。"""

from typing import Annotated

import typer

from vortex import __version__
from vortex.tui.app import run_tui

cli = typer.Typer(
    name="vortex",
    help="Vortex local Agent Runtime.",
    add_completion=False,
    invoke_without_command=True,
    no_args_is_help=False,
)


def _version_callback(value: bool) -> None:
    """在启动 TUI 前处理版本输出。"""
    if value:
        typer.echo(f"Vortex {__version__}")
        raise typer.Exit


@cli.callback()
def root(
    ctx: typer.Context,
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show the Vortex version and exit.",
        ),
    ] = False,
) -> None:
    """无子命令时启动交互式终端界面。"""
    del version
    if ctx.invoked_subcommand is None:
        run_tui()


def main() -> None:
    """供 pyproject.toml 注册为 ``vortex`` 可执行命令。"""
    cli()
