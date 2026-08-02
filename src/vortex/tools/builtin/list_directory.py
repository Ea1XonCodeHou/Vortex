"""受工作区约束的目录浏览工具。"""

import asyncio
from collections.abc import Mapping
from itertools import islice
from pathlib import Path
from typing import cast

from pydantic import BaseModel, ConfigDict, Field

from vortex.domain.tools import ToolDefinition, ToolErrorCode, ToolResult, ToolRisk
from vortex.tools.base import BaseTool
from vortex.tools.builtin.filters import SKIPPED_DIRECTORIES
from vortex.tools.errors import ToolInvocationError
from vortex.tools.workspace import Workspace

_MAX_DEPTH = 4
_MAX_ENTRIES = 200


class ListDirectoryArguments(BaseModel):
    """目录浏览参数。"""

    model_config = ConfigDict(extra="forbid")

    path: str = "."
    max_depth: int = Field(default=2, ge=1, le=_MAX_DEPTH)


class ListDirectoryTool(BaseTool):
    """以受限树形结构列出工作区目录。"""

    definition = ToolDefinition(
        name="list_directory",
        description=(
            "List files and directories inside the current workspace as a bounded tree. "
            "Use this first when you need to discover a project's structure."
        ),
        input_schema=cast(dict[str, object], ListDirectoryArguments.model_json_schema()),
        risk=ToolRisk.READ,
    )

    def __init__(self, workspace: Workspace) -> None:
        self._workspace = workspace

    async def invoke(self, arguments: Mapping[str, object]) -> ToolResult:
        params = ListDirectoryArguments.model_validate(dict(arguments))
        return await asyncio.to_thread(self._list, params)

    def _list(self, params: ListDirectoryArguments) -> ToolResult:
        root = self._workspace.resolve(params.path)
        if not root.is_dir():
            raise ToolInvocationError(
                f"Path is not a directory: {params.path}",
                ToolErrorCode.UNSUPPORTED_CONTENT,
            )

        lines = [f"{self._workspace.display(root)}/"]
        count = 0
        truncated = False

        def walk(directory: Path, depth: int, prefix: str) -> None:
            nonlocal count, truncated
            if depth > params.max_depth or truncated:
                return
            remaining = _MAX_ENTRIES - count
            discovered = list(islice(directory.iterdir(), remaining + 1))
            overflow = len(discovered) > remaining
            entries = sorted(discovered[:remaining], key=_entry_order)
            for index, entry in enumerate(entries):
                if count >= _MAX_ENTRIES:
                    lines.append(f"{prefix}... [truncated after {_MAX_ENTRIES} entries]")
                    truncated = True
                    return

                is_symlink = entry.is_symlink()
                is_directory = entry.is_dir() and not is_symlink
                connector = "└── " if index == len(entries) - 1 else "├── "
                suffix = "@" if is_symlink else "/" if is_directory else ""
                lines.append(f"{prefix}{connector}{entry.name}{suffix}")
                count += 1

                should_descend = (
                    is_directory
                    and depth < params.max_depth
                    and entry.name not in SKIPPED_DIRECTORIES
                )
                if should_descend:
                    extension = "    " if index == len(entries) - 1 else "│   "
                    walk(entry, depth + 1, prefix + extension)

            if overflow and not truncated:
                lines.append(f"{prefix}... [truncated after {_MAX_ENTRIES} entries]")
                truncated = True

        walk(root, 1, "")
        return ToolResult.success("\n".join(lines))


def _entry_order(entry: Path) -> tuple[bool, str]:
    """目录优先排序且不跟随符号链接判断目标类型。"""
    is_directory = not entry.is_symlink() and entry.is_dir()
    return (not is_directory, entry.name.lower())
