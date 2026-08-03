"""对现有工作区文本文件执行经过预览和审批的精确编辑。"""

import asyncio
import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from pydantic import BaseModel, ConfigDict, Field

from vortex.domain.tools import ToolCall, ToolDefinition, ToolErrorCode, ToolResult, ToolRisk
from vortex.tools.base import BaseTool, ToolPreparation
from vortex.tools.changes import (
    TurnChangeTracker,
    atomic_replace_file,
    diff_counts,
    file_mode,
    unified_diff,
)
from vortex.tools.errors import ToolInvocationError
from vortex.tools.workspace import Workspace

_MAX_FILE_BYTES = 2 * 1024 * 1024
_MAX_EDIT_CHARACTERS = 128 * 1024
_MAX_EDITS = 20


class TextEdit(BaseModel):
    """一次必须精确匹配原文的局部替换。"""

    model_config = ConfigDict(extra="forbid")

    old_text: str = Field(min_length=1, max_length=_MAX_EDIT_CHARACTERS)
    new_text: str = Field(max_length=_MAX_EDIT_CHARACTERS)


class ApplyPatchArguments(BaseModel):
    """单个现有文件的结构化 Patch 参数。"""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=1_000)
    edits: list[TextEdit] = Field(min_length=1, max_length=_MAX_EDITS)


@dataclass(frozen=True, slots=True)
class _PreparedPatch:
    path: Path
    display_path: str
    before: bytes
    after: bytes
    before_digest: bytes
    mode: int
    diff: str
    additions: int
    deletions: int
    edit_count: int


class ApplyPatchTool(BaseTool):
    """精确修改一个现有 UTF-8 文件，不支持创建、删除或重命名。"""

    definition = ToolDefinition(
        name="apply_patch",
        description=(
            "Apply exact text replacements to one existing UTF-8 file in the current workspace. "
            "Read the file first and copy old_text exactly. Each old_text must occur exactly "
            "once. This tool cannot create, delete, rename, or access symbolic links."
        ),
        input_schema=cast(dict[str, object], ApplyPatchArguments.model_json_schema()),
        risk=ToolRisk.WRITE,
    )

    def __init__(self, workspace: Workspace, changes: TurnChangeTracker) -> None:
        self._workspace = workspace
        self._changes = changes

    async def prepare(self, call: ToolCall) -> ToolPreparation:
        params = ApplyPatchArguments.model_validate(call.arguments)
        prepared = await asyncio.to_thread(self._prepare_sync, params)
        return ToolPreparation(
            call=call,
            approval_preview=prepared.diff,
            payload=prepared,
        )

    async def invoke(self, arguments: Mapping[str, object]) -> ToolResult:
        call = ToolCall(id="direct", name=self.definition.name, arguments=dict(arguments))
        return await self.invoke_prepared(await self.prepare(call))

    async def invoke_prepared(self, preparation: ToolPreparation) -> ToolResult:
        if not isinstance(preparation.payload, _PreparedPatch):
            raise ToolInvocationError(
                "The prepared patch payload is invalid.",
                ToolErrorCode.INVALID_ARGUMENTS,
            )
        prepared = preparation.payload
        self._changes.ensure_active()
        task = asyncio.create_task(asyncio.to_thread(self._commit_sync, prepared))
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            await task
            await self._record_or_rollback(prepared)
            raise
        await self._record_or_rollback(prepared)
        noun = "edit" if prepared.edit_count == 1 else "edits"
        return ToolResult.success(
            f"Updated {prepared.display_path}: {prepared.edit_count} {noun}, "
            f"+{prepared.additions} -{prepared.deletions}."
        )

    def _prepare_sync(self, params: ApplyPatchArguments) -> _PreparedPatch:
        path = self._workspace.resolve_mutation_target(params.path)
        if not path.is_file():
            raise ToolInvocationError(
                f"Path is not a regular file: {params.path}",
                ToolErrorCode.UNSUPPORTED_CONTENT,
            )
        if path.stat().st_size > _MAX_FILE_BYTES:
            raise ToolInvocationError(
                f"File exceeds the {_MAX_FILE_BYTES}-byte patch limit: {params.path}",
                ToolErrorCode.UNSUPPORTED_CONTENT,
            )
        before = path.read_bytes()
        if b"\x00" in before[:4096]:
            raise ToolInvocationError(
                f"File appears to be binary: {params.path}",
                ToolErrorCode.UNSUPPORTED_CONTENT,
            )
        try:
            text = before.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ToolInvocationError(
                f"File is not valid UTF-8 text: {params.path}",
                ToolErrorCode.UNSUPPORTED_CONTENT,
            ) from exc

        total_characters = sum(len(edit.old_text) + len(edit.new_text) for edit in params.edits)
        if total_characters > _MAX_EDIT_CHARACTERS:
            raise ToolInvocationError(
                f"Patch exceeds the {_MAX_EDIT_CHARACTERS}-character limit.",
                ToolErrorCode.INVALID_ARGUMENTS,
            )

        replacements: list[tuple[int, int, str]] = []
        for edit in params.edits:
            if edit.old_text == edit.new_text:
                raise ToolInvocationError(
                    "Patch contains an edit with no content change.",
                    ToolErrorCode.INVALID_ARGUMENTS,
                )
            occurrences = text.count(edit.old_text)
            if occurrences == 0:
                raise ToolInvocationError(
                    "Patch old_text was not found in the current file.",
                    ToolErrorCode.STALE_FILE,
                )
            if occurrences > 1:
                raise ToolInvocationError(
                    "Patch old_text matches more than one location; include more context.",
                    ToolErrorCode.AMBIGUOUS_MATCH,
                )
            start = text.index(edit.old_text)
            replacements.append((start, start + len(edit.old_text), edit.new_text))

        replacements.sort(key=lambda replacement: replacement[0])
        for previous, current in zip(replacements, replacements[1:], strict=False):
            if current[0] < previous[1]:
                raise ToolInvocationError(
                    "Patch edits overlap in the original file.",
                    ToolErrorCode.INVALID_ARGUMENTS,
                )

        parts: list[str] = []
        cursor = 0
        for start, end, replacement in replacements:
            parts.append(text[cursor:start])
            parts.append(replacement)
            cursor = end
        parts.append(text[cursor:])
        after_text = "".join(parts)
        display_path = self._workspace.display(path)
        diff = unified_diff(display_path, text, after_text)
        additions, deletions = diff_counts(diff)
        return _PreparedPatch(
            path=path,
            display_path=display_path,
            before=before,
            after=after_text.encode("utf-8"),
            before_digest=hashlib.sha256(before).digest(),
            mode=file_mode(path),
            diff=diff,
            additions=additions,
            deletions=deletions,
            edit_count=len(params.edits),
        )

    def _commit_sync(self, prepared: _PreparedPatch) -> None:
        current = prepared.path.read_bytes()
        if hashlib.sha256(current).digest() != prepared.before_digest:
            raise ToolInvocationError(
                "The file changed after the patch preview. Read it again and prepare a new patch.",
                ToolErrorCode.STALE_FILE,
            )
        self._changes.validate_before_mutation(prepared.path, current)
        atomic_replace_file(prepared.path, prepared.after, prepared.mode)

    async def _record_or_rollback(self, prepared: _PreparedPatch) -> None:
        try:
            self._changes.record_change(
                prepared.path,
                prepared.before,
                prepared.after,
                prepared.mode,
            )
        except Exception:
            await asyncio.to_thread(
                atomic_replace_file,
                prepared.path,
                prepared.before,
                prepared.mode,
            )
            raise
