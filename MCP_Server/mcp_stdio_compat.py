"""Windows stdio compatibility helpers for MCP SDK."""

from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from io import TextIOWrapper
from typing import Any


def patch_stdio_for_windows() -> Any | None:
    """Patch MCP stdio on Windows so JSON-RPC lines use LF instead of CRLF."""
    if sys.platform != "win32":
        return None

    import anyio
    import anyio.lowlevel
    import mcp.server.stdio as mcp_stdio
    import mcp.types as types
    import msvcrt
    from mcp.shared.message import SessionMessage

    msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
    msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)

    @asynccontextmanager
    async def _patched_stdio_server(stdin=None, stdout=None):
        if not stdin:
            stdin = anyio.wrap_file(
                TextIOWrapper(sys.stdin.buffer, encoding="utf-8", newline="\n")
            )
        if not stdout:
            stdout = anyio.wrap_file(
                TextIOWrapper(sys.stdout.buffer, encoding="utf-8", newline="\n")
            )

        read_stream_writer, read_stream = anyio.create_memory_object_stream(0)
        write_stream, write_stream_reader = anyio.create_memory_object_stream(0)

        async def stdin_reader():
            try:
                async with read_stream_writer:
                    async for line in stdin:
                        try:
                            message = types.JSONRPCMessage.model_validate_json(line)
                        except Exception as exc:
                            await read_stream_writer.send(exc)
                            continue
                        await read_stream_writer.send(SessionMessage(message))
            except anyio.ClosedResourceError:
                await anyio.lowlevel.checkpoint()

        async def stdout_writer():
            try:
                async with write_stream_reader:
                    async for session_message in write_stream_reader:
                        payload = session_message.message.model_dump_json(
                            by_alias=True,
                            exclude_none=True,
                        )
                        await stdout.write(payload + "\n")
                        await stdout.flush()
            except anyio.ClosedResourceError:
                await anyio.lowlevel.checkpoint()

        async with anyio.create_task_group() as task_group:
            task_group.start_soon(stdin_reader)
            task_group.start_soon(stdout_writer)
            yield read_stream, write_stream

    mcp_stdio.stdio_server = _patched_stdio_server
    return _patched_stdio_server
