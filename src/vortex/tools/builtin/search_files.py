"""受工作区约束的文本内容搜索工具。"""

import asyncio
import os
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from pydantic import BaseModel, ConfigDict, Field

from vortex.domain.tools import ToolDefinition, ToolErrorCode, ToolResult, ToolRisk
from vortex.tools.base import BaseTool
from vortex.tools.builtin.filters import SKIPPED_DIRECTORIES
from vortex.tools.errors import ToolInvocationError
from vortex.tools.workspace import Workspace

_MAX_FILE_BYTES = 1024 * 1024
_MAX_FILES = 2_000


class SearchFilesArguments(BaseModel):
    """文本搜索参数。"""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=200)
    path: str = "."
    max_results: int = Field(default=100, ge=1, le=200)
    case_sensitive: bool = False


class SearchFilesTool(BaseTool):
    """搜索工作区内受限数量的 UTF-8 文本文件。"""

    definition = ToolDefinition(
        name="search_files",
        description=(
            "Search for a literal text string inside UTF-8 files in the current workspace. "
            "Returns bounded path, line number, and matching-line previews."
        ),
        input_schema=cast(dict[str, object], SearchFilesArguments.model_json_schema()),
        risk=ToolRisk.READ,
    )

    def __init__(self, workspace: Workspace) -> None:
        self._workspace = workspace

    async def invoke(self, arguments: Mapping[str, object]) -> ToolResult:
        params = SearchFilesArguments.model_validate(dict(arguments))
        return await asyncio.to_thread(self._search, params)

    def _search(self, params: SearchFilesArguments) -> ToolResult:
        root = self._workspace.resolve(params.path)
        if not root.is_dir():
            raise ToolInvocationError(
                f"Path is not a directory: {params.path}",
                ToolErrorCode.UNSUPPORTED_CONTENT,
            )

        needle = params.query if params.case_sensitive else params.query.casefold()
        matches: list[str] = []
        files_seen = 0
        truncated = False

        for directory, dir_names, file_names in os.walk(root, followlinks=False):
            dir_names[:] = sorted(name for name in dir_names if name not in SKIPPED_DIRECTORIES)
            for file_name in sorted(file_names):
                if files_seen >= _MAX_FILES or len(matches) >= params.max_results:
                    truncated = True
                    break
                path = Path(directory, file_name)
                if path.is_symlink() or not path.is_file():
                    continue
                files_seen += 1
                try:
                    if path.stat().st_size > _MAX_FILE_BYTES:
                        continue
                    raw = path.read_bytes()
                    if b"\x00" in raw[:4096]:
                        continue
                    text = raw.decode("utf-8")
                except (OSError, UnicodeDecodeError):
                    continue

                for line_number, line in enumerate(text.splitlines(), start=1):
                    haystack = line if params.case_sensitive else line.casefold()
                    if needle in haystack:
                        preview = line.strip()
                        if len(preview) > 300:
                            preview = preview[:297] + "..."
                        relative = self._workspace.display(path)
                        matches.append(f"{relative}:{line_number}: {preview}")
                        if len(matches) >= params.max_results:
                            truncated = True
                            break
            if truncated:
                break

        if not matches:
            return ToolResult.success(f'No matches found for "{params.query}".')
        suffix = "\n[results truncated]" if truncated else ""
        return ToolResult.success("\n".join(matches) + suffix)
