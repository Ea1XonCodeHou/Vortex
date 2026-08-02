"""Vortex 顶层包。"""

from importlib.metadata import PackageNotFoundError, version

try:
    # 版本以 pyproject.toml 中的包元数据为唯一来源。
    __version__ = version("vortex-agent")
except PackageNotFoundError:
    # 仅在源码未安装、被直接导入时使用，正常安装不会进入此分支。
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
