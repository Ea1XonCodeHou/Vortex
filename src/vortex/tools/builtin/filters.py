"""内置工作区工具共享的目录过滤规则。"""

SKIPPED_DIRECTORIES = frozenset(
    {
        ".git",
        ".idea",
        ".mypy_cache",
        ".next",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "coverage",
        "dist",
        "node_modules",
        "target",
    }
)

__all__ = ["SKIPPED_DIRECTORIES"]
