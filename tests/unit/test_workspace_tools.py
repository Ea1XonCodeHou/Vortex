"""只读工作区工具的行为与安全边界测试。"""

import re
from pathlib import Path

from vortex.domain.tools import ToolCall, ToolErrorCode
from vortex.tools.builtin import build_workspace_registry
from vortex.tools.executor import ToolExecutor


async def test_workspace_tools_list_read_and_search_real_files(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "agent.py").write_text(
        "class AgentRuntime:\n    pass\n",
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text("# Demo\nAgent Runtime project\n", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "ignored").write_text("AgentRuntime", encoding="utf-8")
    executor = ToolExecutor(build_workspace_registry(tmp_path))

    listed = await executor.execute(
        ToolCall(id="1", name="list_directory", arguments={"path": ".", "max_depth": 2})
    )
    read = await executor.execute(
        ToolCall(id="2", name="read_file", arguments={"path": "README.md"})
    )
    searched = await executor.execute(
        ToolCall(id="3", name="search_files", arguments={"query": "AgentRuntime"})
    )
    overview = await executor.execute(
        ToolCall(id="4", name="workspace_overview", arguments={"path": "."})
    )

    assert "README.md" in listed.result.content
    assert "src/" in listed.result.content
    assert ".git/" in listed.result.content
    assert "[file: README.md | bytes 0-" in read.result.content
    assert "| complete]" in read.result.content
    assert "Agent Runtime project" in read.result.content
    assert "src/agent.py:1: class AgentRuntime:" in searched.result.content
    assert ".git/ignored" not in searched.result.content
    assert "README.md" in overview.result.content
    assert ".py: 1" in overview.result.content
    assert ".git/ignored" not in overview.result.content


async def test_tools_reject_parent_absolute_and_symlink_escape(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("private", encoding="utf-8")
    (workspace / "escape.txt").symlink_to(outside)
    executor = ToolExecutor(build_workspace_registry(workspace))

    parent = await executor.execute(
        ToolCall(id="1", name="read_file", arguments={"path": "../outside.txt"})
    )
    absolute = await executor.execute(
        ToolCall(id="2", name="read_file", arguments={"path": str(outside)})
    )
    symlink = await executor.execute(
        ToolCall(id="3", name="read_file", arguments={"path": "escape.txt"})
    )

    assert parent.result.error_code is ToolErrorCode.ACCESS_DENIED
    assert absolute.result.error_code is ToolErrorCode.ACCESS_DENIED
    assert symlink.result.error_code is ToolErrorCode.ACCESS_DENIED
    assert "private" not in parent.result.content + absolute.result.content + symlink.result.content


async def test_read_file_rejects_binary_and_executor_validates_arguments(tmp_path: Path) -> None:
    (tmp_path / "binary.dat").write_bytes(b"abc\x00def")
    executor = ToolExecutor(build_workspace_registry(tmp_path))

    binary = await executor.execute(
        ToolCall(id="1", name="read_file", arguments={"path": "binary.dat"})
    )
    invalid = await executor.execute(
        ToolCall(id="2", name="read_file", arguments={"unexpected": True})
    )

    assert binary.result.error_code is ToolErrorCode.UNSUPPORTED_CONTENT
    assert invalid.result.error_code is ToolErrorCode.INVALID_ARGUMENTS
    assert "unexpected" in invalid.result.content


async def test_read_file_can_continue_until_a_large_utf8_file_is_complete(tmp_path: Path) -> None:
    expected = ("Vortex 大文件分块读取\n" * 20_000) + "complete"
    path = tmp_path / "large.txt"
    path.write_text(expected, encoding="utf-8")
    assert path.stat().st_size > 256 * 1024
    executor = ToolExecutor(build_workspace_registry(tmp_path))
    offset = 0
    chunks: list[str] = []

    while True:
        execution = await executor.execute(
            ToolCall(
                id=f"read-{offset}",
                name="read_file",
                arguments={"path": "large.txt", "offset": offset},
            )
        )
        assert execution.result.is_error is False
        header, content = execution.result.content.split("\n", 1)
        chunks.append(content)
        match = re.search(r"next_offset=(\d+)", header)
        if match is None:
            assert "| complete]" in header
            break
        next_offset = int(match.group(1))
        assert next_offset > offset
        offset = next_offset

    assert "".join(chunks) == expected
