"""Vortex 源码项目的固定路径。"""

from pathlib import Path

# 当前阶段通过 editable install 运行，私有模型配置固定属于 Vortex 源码项目，
# 不能随着 Agent 工作区的 current working directory 改变。
VORTEX_PROJECT_ROOT = Path(__file__).resolve().parents[3]
VORTEX_ENV_FILE = VORTEX_PROJECT_ROOT / ".env"

__all__ = ["VORTEX_ENV_FILE", "VORTEX_PROJECT_ROOT"]
