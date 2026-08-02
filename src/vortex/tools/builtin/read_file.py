"""受工作区约束的文本文件读取工具。"""

import asyncio
from collections.abc import Mapping
from typing import cast

from pydantic import BaseModel, ConfigDict, Field

from vortex.domain.tools import ToolDefinition, ToolErrorCode, ToolResult, ToolRisk
from vortex.tools.base import BaseTool
from vortex.tools.errors import ToolInvocationError
from vortex.tools.workspace import Workspace

_DEFAULT_CHUNK_BYTES = 64 * 1024
_MAX_CHUNK_BYTES = 128 * 1024


class ReadFileArguments(BaseModel):
    """文件读取参数。"""

    model_config = ConfigDict(extra="forbid")

    path: str
    offset: int = Field(default=0, ge=0)
    max_bytes: int = Field(default=_DEFAULT_CHUNK_BYTES, ge=4, le=_MAX_CHUNK_BYTES)


class ReadFileTool(BaseTool):
    """读取工作区内有大小上限的 UTF-8 文本。"""

    definition = ToolDefinition(
        name="read_file",
        description=(
            "Read a bounded UTF-8 byte chunk from a text file inside the current workspace. "
            "The result reports next_offset when more content remains; call read_file again with "
            "that exact offset to read the complete file without loading it into one model turn. "
            "Use paths discovered with list_directory or search_files."
        ),
        input_schema=cast(dict[str, object], ReadFileArguments.model_json_schema()),
        risk=ToolRisk.READ,
    )

    def __init__(self, workspace: Workspace) -> None:
        self._workspace = workspace

    async def invoke(self, arguments: Mapping[str, object]) -> ToolResult:
        params = ReadFileArguments.model_validate(dict(arguments))
        return await asyncio.to_thread(self._read, params)

    def _read(self, params: ReadFileArguments) -> ToolResult:
        path = self._workspace.resolve(params.path)
        if not path.is_file():
            raise ToolInvocationError(
                f"Path is not a regular file: {params.path}",
                ToolErrorCode.UNSUPPORTED_CONTENT,
            )

        file_size = path.stat().st_size
        if params.offset > file_size:
            raise ToolInvocationError(
                f"Offset {params.offset} is beyond the end of file ({file_size} bytes).",
                ToolErrorCode.INVALID_ARGUMENTS,
            )

        with path.open("rb") as stream:
            stream.seek(params.offset)
            raw = stream.read(params.max_bytes)

        if params.offset == 0 and b"\x00" in raw[:4096]:
            raise ToolInvocationError(
                f"File appears to be binary: {params.path}",
                ToolErrorCode.UNSUPPORTED_CONTENT,
            )

        decoded_raw = raw
        try:
            text = decoded_raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            if exc.reason != "unexpected end of data" or exc.end != len(decoded_raw):
                message = (
                    f"Offset {params.offset} is not aligned to a UTF-8 character boundary."
                    if exc.start == 0 and params.offset > 0
                    else f"File is not valid UTF-8 text: {params.path}"
                )
                code = (
                    ToolErrorCode.INVALID_ARGUMENTS
                    if exc.start == 0 and params.offset > 0
                    else ToolErrorCode.UNSUPPORTED_CONTENT
                )
                raise ToolInvocationError(message, code) from exc
            decoded_raw = decoded_raw[: exc.start]
            if not decoded_raw and raw:
                raise ToolInvocationError(
                    f"File is not valid UTF-8 text: {params.path}",
                    ToolErrorCode.UNSUPPORTED_CONTENT,
                ) from exc
            text = decoded_raw.decode("utf-8")

        end_offset = params.offset + len(decoded_raw)
        has_more = end_offset < file_size
        location = f"bytes {params.offset}-{end_offset} of {file_size}"
        continuation = f" | next_offset={end_offset}" if has_more else " | complete"
        header = f"[file: {self._workspace.display(path)} | {location}{continuation}]"
        return ToolResult.success(f"{header}\n{text}")
