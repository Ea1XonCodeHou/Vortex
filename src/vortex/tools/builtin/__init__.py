"""Vortex 首期只读工作区工具。"""

from pathlib import Path

from vortex.tools.builtin.list_directory import ListDirectoryTool
from vortex.tools.builtin.read_file import ReadFileTool
from vortex.tools.builtin.search_files import SearchFilesTool
from vortex.tools.builtin.workspace_overview import WorkspaceOverviewTool
from vortex.tools.registry import ToolRegistry
from vortex.tools.workspace import Workspace


def build_workspace_registry(root: Path) -> ToolRegistry:
    """为一个工作区创建默认只读工具注册表。"""
    workspace = Workspace(root)
    return ToolRegistry(
        (
            ListDirectoryTool(workspace),
            WorkspaceOverviewTool(workspace),
            ReadFileTool(workspace),
            SearchFilesTool(workspace),
        )
    )


__all__ = [
    "ListDirectoryTool",
    "ReadFileTool",
    "SearchFilesTool",
    "WorkspaceOverviewTool",
    "build_workspace_registry",
]
