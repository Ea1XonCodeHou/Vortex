"""所有本地工具共享的工作区路径边界。"""

from dataclasses import dataclass
from pathlib import Path

from vortex.domain.tools import ToolErrorCode
from vortex.tools.errors import ToolInvocationError


@dataclass(frozen=True, slots=True)
class Workspace:
    """将工具可访问范围固定在启动目录内。"""

    root: Path

    def __post_init__(self) -> None:
        resolved = self.root.expanduser().resolve()
        if not resolved.is_dir():
            raise ValueError(f"Workspace is not a directory: {resolved}")
        object.__setattr__(self, "root", resolved)

    def resolve(self, raw_path: str, *, must_exist: bool = True) -> Path:
        """解析相对路径并拒绝绝对路径、穿越和符号链接逃逸。"""
        candidate_path = Path(raw_path)
        if candidate_path.is_absolute():
            raise ToolInvocationError(
                "Absolute paths are not allowed. Use a path relative to the workspace.",
                ToolErrorCode.ACCESS_DENIED,
            )

        candidate = (self.root / candidate_path).resolve(strict=False)
        if not candidate.is_relative_to(self.root):
            raise ToolInvocationError(
                "The requested path is outside the workspace.",
                ToolErrorCode.ACCESS_DENIED,
            )
        if must_exist and not candidate.exists():
            raise ToolInvocationError(
                f"Path does not exist: {raw_path}",
                ToolErrorCode.NOT_FOUND,
            )
        return candidate

    def display(self, path: Path) -> str:
        """把绝对路径转换成不泄露主机目录的工作区相对路径。"""
        relative = path.relative_to(self.root)
        return relative.as_posix() or "."
