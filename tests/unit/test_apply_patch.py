"""apply_patch 的原子写入、快照与安全撤销测试。"""

import os
from pathlib import Path

from vortex.domain.changes import RevertStatus
from vortex.domain.tools import ToolCall, ToolErrorCode
from vortex.tools.builtin.apply_patch import ApplyPatchTool
from vortex.tools.changes import TurnChangeTracker
from vortex.tools.executor import ToolExecutor
from vortex.tools.registry import ToolRegistry
from vortex.tools.workspace import Workspace


def _call(old: str, new: str, *, identifier: str = "patch-1") -> ToolCall:
    return ToolCall(
        id=identifier,
        name="apply_patch",
        arguments={
            "path": "example.py",
            "edits": [{"old_text": old, "new_text": new}],
        },
    )


def _tool(tmp_path: Path) -> tuple[ApplyPatchTool, TurnChangeTracker]:
    workspace = Workspace(tmp_path)
    tracker = TurnChangeTracker(workspace)
    return ApplyPatchTool(workspace, tracker), tracker


async def test_patch_previews_writes_and_reverts_existing_file(tmp_path: Path) -> None:
    target = tmp_path / "example.py"
    target.write_text("answer = 1\n", encoding="utf-8")
    target.chmod(0o640)
    tool, tracker = _tool(tmp_path)
    tracker.begin_turn("run-1")

    prepared = await tool.prepare(_call("answer = 1", "answer = 2"))
    assert "-answer = 1" in prepared.approval_preview
    assert "+answer = 2" in prepared.approval_preview

    result = await tool.invoke_prepared(prepared)
    summary = tracker.finish_turn("run-1")

    assert result.is_error is False
    assert target.read_text(encoding="utf-8") == "answer = 2\n"
    assert summary is not None
    assert summary.files[0].path == "example.py"
    assert (summary.additions, summary.deletions) == (1, 1)
    assert os.stat(target).st_mode & 0o777 == 0o640

    reverted = await tracker.revert_latest("run-1")
    assert reverted.status is RevertStatus.REVERTED
    assert target.read_text(encoding="utf-8") == "answer = 1\n"


async def test_multiple_patches_revert_to_state_before_first_edit(tmp_path: Path) -> None:
    target = tmp_path / "example.py"
    target.write_text("state = 'A'\n", encoding="utf-8")
    tool, tracker = _tool(tmp_path)
    tracker.begin_turn("run-1")

    first = await tool.prepare(_call("'A'", "'B'", identifier="patch-1"))
    await tool.invoke_prepared(first)
    second = await tool.prepare(_call("'B'", "'D'", identifier="patch-2"))
    await tool.invoke_prepared(second)
    summary = tracker.finish_turn("run-1")

    assert target.read_text(encoding="utf-8") == "state = 'D'\n"
    assert summary is not None
    assert "-state = 'A'" in summary.diff
    assert "+state = 'D'" in summary.diff

    await tracker.revert_latest("run-1")
    assert target.read_text(encoding="utf-8") == "state = 'A'\n"


async def test_ambiguous_or_missing_match_never_writes(tmp_path: Path) -> None:
    target = tmp_path / "example.py"
    target.write_text("value = 1\nvalue = 1\n", encoding="utf-8")
    tool, tracker = _tool(tmp_path)
    tracker.begin_turn("run-1")
    executor = ToolExecutor(ToolRegistry((tool,)))

    ambiguous = await executor.execute(_call("value = 1", "value = 2"))
    missing = await executor.execute(_call("missing", "replacement", identifier="patch-2"))

    assert ambiguous.result.error_code is ToolErrorCode.AMBIGUOUS_MATCH
    assert missing.result.error_code is ToolErrorCode.STALE_FILE
    assert target.read_text(encoding="utf-8") == "value = 1\nvalue = 1\n"


async def test_file_change_after_preview_blocks_commit(tmp_path: Path) -> None:
    target = tmp_path / "example.py"
    target.write_text("value = 1\n", encoding="utf-8")
    tool, tracker = _tool(tmp_path)
    tracker.begin_turn("run-1")
    executor = ToolExecutor(ToolRegistry((tool,)))
    prepared = await executor.prepare(_call("value = 1", "value = 2"))
    assert prepared.preparation is not None
    target.write_text("external = True\n", encoding="utf-8")

    execution = await executor.execute_prepared(prepared.preparation)

    assert execution.result.error_code is ToolErrorCode.STALE_FILE
    assert target.read_text(encoding="utf-8") == "external = True\n"


async def test_external_change_blocks_whole_turn_revert(tmp_path: Path) -> None:
    target = tmp_path / "example.py"
    target.write_text("value = 1\n", encoding="utf-8")
    tool, tracker = _tool(tmp_path)
    tracker.begin_turn("run-1")
    await tool.invoke_prepared(await tool.prepare(_call("value = 1", "value = 2")))
    tracker.finish_turn("run-1")
    target.write_text("user = 3\n", encoding="utf-8")

    result = await tracker.revert_latest("run-1")

    assert result.status is RevertStatus.CONFLICT
    assert result.paths == ("example.py",)
    assert target.read_text(encoding="utf-8") == "user = 3\n"


async def test_starting_next_turn_accepts_previous_changes(tmp_path: Path) -> None:
    target = tmp_path / "example.py"
    target.write_text("value = 1\n", encoding="utf-8")
    tool, tracker = _tool(tmp_path)
    tracker.begin_turn("run-1")
    await tool.invoke_prepared(await tool.prepare(_call("value = 1", "value = 2")))
    tracker.finish_turn("run-1")

    tracker.begin_turn("run-2")
    result = await tracker.revert_latest("run-1")

    assert result.status is RevertStatus.UNAVAILABLE
    assert target.read_text(encoding="utf-8") == "value = 2\n"


async def test_patch_cannot_create_or_follow_symlink(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside.py"
    outside.write_text("safe = True\n", encoding="utf-8")
    (tmp_path / "example.py").symlink_to(outside)
    tool, tracker = _tool(tmp_path)
    tracker.begin_turn("run-1")
    executor = ToolExecutor(ToolRegistry((tool,)))

    symlink_result = await executor.execute(_call("safe = True", "safe = False"))
    create_call = ToolCall(
        id="patch-2",
        name="apply_patch",
        arguments={
            "path": "missing.py",
            "edits": [{"old_text": "a", "new_text": "b"}],
        },
    )
    create_result = await executor.execute(create_call)

    assert symlink_result.result.is_error is True
    assert create_result.result.error_code is ToolErrorCode.NOT_FOUND
    assert outside.read_text(encoding="utf-8") == "safe = True\n"
    outside.unlink()
