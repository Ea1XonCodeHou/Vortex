"""一次 Agent Run 产生的工作区变更摘要与撤销结果。"""

from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class FileChangeSummary:
    """一个文件在当前 Run 开始前后之间的净变化。"""

    path: str
    additions: int
    deletions: int


@dataclass(frozen=True, slots=True)
class TurnChangeSummary:
    """当前最新 Run 中由 Vortex 直接编辑产生的净变化。"""

    run_id: str
    files: tuple[FileChangeSummary, ...]
    additions: int
    deletions: int
    diff: str


class RevertStatus(StrEnum):
    """最新 Run 整体撤销的稳定结果。"""

    REVERTED = "reverted"
    CONFLICT = "conflict"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class RevertResult:
    """用户请求撤销最新 Run 文件变化后的结果。"""

    status: RevertStatus
    paths: tuple[str, ...] = ()
    message: str = ""
