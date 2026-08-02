"""面向大型仓库的有界结构概览工具。"""

import asyncio
import os
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from pydantic import BaseModel, ConfigDict, Field

from vortex.domain.tools import ToolDefinition, ToolErrorCode, ToolResult, ToolRisk
from vortex.tools.base import BaseTool
from vortex.tools.builtin.filters import SKIPPED_DIRECTORIES
from vortex.tools.errors import ToolInvocationError
from vortex.tools.workspace import Workspace

_DEFAULT_MAX_FILES = 10_000
_MAX_FILES = 50_000
_KEY_FILE_NAMES = frozenset(
    {
        "AGENTS.md",
        "Cargo.toml",
        "Dockerfile",
        "Makefile",
        "README.md",
        "build.gradle",
        "go.mod",
        "package.json",
        "pom.xml",
        "pyproject.toml",
        "requirements.txt",
        "settings.gradle",
    }
)


class WorkspaceOverviewArguments(BaseModel):
    """大型工作区概览参数。"""

    model_config = ConfigDict(extra="forbid")

    path: str = "."
    max_files: int = Field(default=_DEFAULT_MAX_FILES, ge=100, le=_MAX_FILES)


class WorkspaceOverviewTool(BaseTool):
    """生成有界文件清单统计，帮助模型先建立仓库地图。"""

    definition = ToolDefinition(
        name="workspace_overview",
        description=(
            "Build a bounded structural overview of a workspace or subdirectory: top-level "
            "entries, file and directory counts, dominant extensions, key project files, and "
            "largest files. Use this first for broad repository analysis before targeted reads."
        ),
        input_schema=cast(dict[str, object], WorkspaceOverviewArguments.model_json_schema()),
        risk=ToolRisk.READ,
    )

    def __init__(self, workspace: Workspace) -> None:
        self._workspace = workspace

    async def invoke(self, arguments: Mapping[str, object]) -> ToolResult:
        params = WorkspaceOverviewArguments.model_validate(dict(arguments))
        return await asyncio.to_thread(self._overview, params)

    def _overview(self, params: WorkspaceOverviewArguments) -> ToolResult:
        root = self._workspace.resolve(params.path)
        if not root.is_dir():
            raise ToolInvocationError(
                f"Path is not a directory: {params.path}",
                ToolErrorCode.UNSUPPORTED_CONTENT,
            )

        top_level = _top_level_entries(root)
        extensions: Counter[str] = Counter()
        key_files: list[str] = []
        largest_files: list[tuple[int, str]] = []
        file_count = 0
        directory_count = 0
        total_bytes = 0
        truncated = False

        for directory, dir_names, file_names in os.walk(root, followlinks=False):
            dir_names[:] = sorted(
                name
                for name in dir_names
                if name not in SKIPPED_DIRECTORIES and not Path(directory, name).is_symlink()
            )
            directory_count += len(dir_names)
            for file_name in sorted(file_names):
                if file_count >= params.max_files:
                    truncated = True
                    break
                path = Path(directory, file_name)
                if path.is_symlink() or not path.is_file():
                    continue
                try:
                    size = path.stat().st_size
                except OSError:
                    continue
                relative = self._workspace.display(path)
                file_count += 1
                total_bytes += size
                extension = path.suffix.lower() or "[no extension]"
                extensions[extension] += 1
                if file_name in _KEY_FILE_NAMES:
                    key_files.append(relative)
                largest_files.append((size, relative))
                largest_files.sort(reverse=True)
                del largest_files[10:]
            if truncated:
                break

        lines = [
            f"[workspace overview: {self._workspace.display(root)}]",
            f"files: {file_count}{'+' if truncated else ''}",
            f"directories: {directory_count}{'+' if truncated else ''}",
            f"total bytes scanned: {total_bytes}",
            "top-level: " + (", ".join(top_level) if top_level else "[empty]"),
            "dominant extensions:",
        ]
        lines.extend(f"- {extension}: {count}" for extension, count in extensions.most_common(15))
        lines.append("key project files:")
        lines.extend(f"- {path}" for path in sorted(key_files)[:40])
        if not key_files:
            lines.append("- [none found]")
        lines.append("largest files:")
        lines.extend(f"- {path}: {size} bytes" for size, path in largest_files)
        if not largest_files:
            lines.append("- [none found]")
        if truncated:
            lines.append(f"[scan truncated after {params.max_files} files]")
        return ToolResult.success("\n".join(lines))


def _top_level_entries(root: Path) -> list[str]:
    """列出不包含依赖缓存的顶层入口。"""
    entries: list[str] = []
    for entry in root.iterdir():
        if entry.name in SKIPPED_DIRECTORIES or entry.is_symlink():
            continue
        suffix = "/" if entry.is_dir() else ""
        entries.append(entry.name + suffix)
    return sorted(entries, key=str.casefold)[:100]
