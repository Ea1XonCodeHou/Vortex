"""Vortex 内置工作区工具。"""

from pathlib import Path

from vortex.tools.builtin.apply_patch import ApplyPatchTool
from vortex.tools.builtin.list_directory import ListDirectoryTool
from vortex.tools.builtin.read_file import ReadFileTool
from vortex.tools.builtin.run_command import RunCommandTool
from vortex.tools.builtin.search_files import SearchFilesTool
from vortex.tools.builtin.workspace_overview import WorkspaceOverviewTool
from vortex.tools.changes import TurnChangeTracker
from vortex.tools.registry import ToolRegistry
from vortex.tools.workspace import Workspace


def build_workspace_registry(
    root: Path,
    changes: TurnChangeTracker | None = None,
) -> ToolRegistry:
    """为一个工作区创建默认工具注册表。"""
    workspace = Workspace(root)
    change_tracker = changes or TurnChangeTracker(workspace)
    return ToolRegistry(
        (
            ListDirectoryTool(workspace),
            WorkspaceOverviewTool(workspace),
            ReadFileTool(workspace),
            SearchFilesTool(workspace),
            ApplyPatchTool(workspace, change_tracker),
            RunCommandTool(workspace),
        )
    )


__all__ = [
    "ApplyPatchTool",
    "ListDirectoryTool",
    "ReadFileTool",
    "RunCommandTool",
    "SearchFilesTool",
    "WorkspaceOverviewTool",
    "build_workspace_registry",
]
