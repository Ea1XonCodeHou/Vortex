"""最新 Agent Run 的纯内存文件快照、汇总与整体撤销。"""

import asyncio
import difflib
import hashlib
import os
import stat
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from vortex.domain.changes import (
    FileChangeSummary,
    RevertResult,
    RevertStatus,
    TurnChangeSummary,
)
from vortex.domain.tools import ToolErrorCode
from vortex.tools.errors import ToolInvocationError
from vortex.tools.workspace import Workspace


@dataclass(slots=True)
class _TrackedFile:
    path: Path
    display_path: str
    original_content: bytes
    original_mode: int
    latest_content: bytes


class TurnChangeTracker:
    """只保留当前或最新 Run 的首次文件快照。"""

    def __init__(self, workspace: Workspace) -> None:
        self._workspace = workspace
        self._active_run_id: str | None = None
        self._active: dict[Path, _TrackedFile] = {}
        self._latest_run_id: str | None = None
        self._latest: dict[Path, _TrackedFile] = {}

    def begin_turn(self, run_id: str) -> None:
        """开始新 Run，并接受、丢弃上一轮可撤销快照。"""
        self._latest_run_id = None
        self._latest = {}
        self._active_run_id = run_id
        self._active = {}

    def ensure_active(self) -> None:
        """确保写工具只能在 Agent Runtime 管理的 Run 内提交。"""
        if self._active_run_id is None:
            raise RuntimeError("No active turn is available for file mutation")

    def validate_before_mutation(self, path: Path, current_content: bytes) -> None:
        """拒绝覆盖本轮中发生在 Vortex 写入之外的文件变化。"""
        tracked = self._active.get(path)
        if tracked is not None and tracked.latest_content != current_content:
            raise ToolInvocationError(
                "The file changed outside Vortex after an earlier edit in this turn. "
                "Start a new task after reviewing the external change.",
                ToolErrorCode.STALE_FILE,
            )

    def record_change(self, path: Path, before: bytes, after: bytes, mode: int) -> None:
        """记录一次成功写入；同一文件只保留最初内容。"""
        if self._active_run_id is None:
            raise RuntimeError("No active turn is available for file mutation")
        tracked = self._active.get(path)
        if tracked is None:
            self._active[path] = _TrackedFile(
                path=path,
                display_path=self._workspace.display(path),
                original_content=before,
                original_mode=mode,
                latest_content=after,
            )
            return
        if tracked.latest_content != before:
            raise RuntimeError("File mutation was committed from an untracked base")
        tracked.latest_content = after

    def finish_turn(self, run_id: str) -> TurnChangeSummary | None:
        """冻结当前 Run 的净变化，供 TUI 展示和一次整体撤销。"""
        if self._active_run_id != run_id:
            return None
        tracked = {
            path: change
            for path, change in self._active.items()
            if change.original_content != change.latest_content
        }
        self._active_run_id = None
        self._active = {}
        if not tracked:
            self._latest_run_id = None
            self._latest = {}
            return None

        self._latest_run_id = run_id
        self._latest = tracked
        return _summary(run_id, tracked.values())

    async def revert_latest(self, run_id: str) -> RevertResult:
        """安全恢复最新 Run 的全部文件；任一冲突都会阻止整体恢复。"""
        if self._latest_run_id != run_id or not self._latest:
            return RevertResult(
                RevertStatus.UNAVAILABLE,
                message="The latest turn no longer has changes available to revert.",
            )
        return await asyncio.to_thread(self._revert_latest_sync, run_id)

    def _revert_latest_sync(self, run_id: str) -> RevertResult:
        if self._latest_run_id != run_id or not self._latest:
            return RevertResult(
                RevertStatus.UNAVAILABLE,
                message="The latest turn no longer has changes available to revert.",
            )

        changes = tuple(sorted(self._latest.values(), key=lambda change: change.display_path))
        conflicts: list[str] = []
        for change in changes:
            try:
                current = change.path.read_bytes()
            except OSError:
                conflicts.append(change.display_path)
                continue
            if _digest(current) != _digest(change.latest_content):
                conflicts.append(change.display_path)
        if conflicts:
            return RevertResult(
                RevertStatus.CONFLICT,
                paths=tuple(conflicts),
                message=(
                    "Revert was blocked because files changed outside Vortex after this turn."
                ),
            )

        restored: list[_TrackedFile] = []
        try:
            for change in changes:
                atomic_replace_file(
                    change.path,
                    change.original_content,
                    change.original_mode,
                )
                restored.append(change)
        except OSError:
            rollback_failed = False
            for change in reversed(restored):
                try:
                    atomic_replace_file(
                        change.path,
                        change.latest_content,
                        change.original_mode,
                    )
                except OSError:
                    rollback_failed = True
            message = "Revert failed and the completed restores were rolled back."
            if rollback_failed:
                message = "Revert failed and Vortex could not fully restore the pre-revert state."
            return RevertResult(RevertStatus.FAILED, message=message)

        paths = tuple(change.display_path for change in changes)
        self._latest_run_id = None
        self._latest = {}
        return RevertResult(
            RevertStatus.REVERTED,
            paths=paths,
            message=f"Reverted {len(paths)} file{'s' if len(paths) != 1 else ''}.",
        )


def atomic_replace_file(path: Path, content: bytes, mode: int) -> None:
    """在目标目录写入临时文件并使用原子替换提交。"""
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.vortex-",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def file_mode(path: Path) -> int:
    """返回不包含文件类型位的权限模式。"""
    return stat.S_IMODE(path.stat().st_mode)


def unified_diff(path: str, before: str, after: str) -> str:
    """生成工作区相对路径的标准统一 Diff。"""
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )


def diff_counts(diff: str) -> tuple[int, int]:
    """统计统一 Diff 的实际新增与删除行。"""
    additions = 0
    deletions = 0
    for line in diff.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            additions += 1
        elif line.startswith("-"):
            deletions += 1
    return additions, deletions


def _summary(run_id: str, changes: Iterable[_TrackedFile]) -> TurnChangeSummary:
    tracked = tuple(changes)
    file_summaries: list[FileChangeSummary] = []
    diffs: list[str] = []
    total_additions = 0
    total_deletions = 0
    for change in sorted(tracked, key=lambda item: item.display_path):
        before = change.original_content.decode("utf-8")
        after = change.latest_content.decode("utf-8")
        diff = unified_diff(change.display_path, before, after)
        additions, deletions = diff_counts(diff)
        file_summaries.append(FileChangeSummary(change.display_path, additions, deletions))
        diffs.append(diff)
        total_additions += additions
        total_deletions += deletions
    return TurnChangeSummary(
        run_id=run_id,
        files=tuple(file_summaries),
        additions=total_additions,
        deletions=total_deletions,
        diff="\n".join(diffs),
    )


def _digest(content: bytes) -> bytes:
    return hashlib.sha256(content).digest()
