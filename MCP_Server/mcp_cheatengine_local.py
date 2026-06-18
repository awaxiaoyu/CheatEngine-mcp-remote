#!/usr/bin/env python3
"""Cheat Engine MCP Bridge - local named-pipe client."""

import json
import struct
import sys
import time
import traceback

from ce_tool_specs import register_ce_tools
from mcp_stdio_compat import patch_stdio_for_windows


_patched_stdio_server = patch_stdio_for_windows()

_mcp_stdout = sys.stdout
sys.stdout = sys.stderr
try:
    import pywintypes
    import win32file
    from mcp.server.fastmcp import FastMCP

    if _patched_stdio_server is not None:
        import mcp.server.fastmcp.server as fastmcp_server

        fastmcp_server.stdio_server = _patched_stdio_server
except ImportError as exc:
    print(f"[MCP CE] Import Error: {exc}", file=sys.stderr, flush=True)
    sys.exit(1)
finally:
    sys.stdout = _mcp_stdout


PIPE_NAME = r"\\.\pipe\CE_MCP_Bridge_v99"
MCP_SERVER_NAME = "cheatengine"
MAX_RESPONSE_SIZE = 16 * 1024 * 1024


def debug_log(message: str) -> None:
    print(f"[MCP CE] {message}", file=sys.stderr, flush=True)


def format_result(result):
    if isinstance(result, dict):
        return json.dumps(result, indent=None, ensure_ascii=False)
    if isinstance(result, str):
        return result
    return json.dumps(result, ensure_ascii=False)


class CEBridgeClient:
    def __init__(self):
        self.handle = None

    def connect(self) -> bool:
        try:
            self.handle = win32file.CreateFile(
                PIPE_NAME,
                win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                0,
                None,
                win32file.OPEN_EXISTING,
                0,
                None,
            )
            return True
        except pywintypes.error:
            return False

    def _read_exact(self, size: int) -> bytes:
        chunks = []
        remaining = size
        while remaining > 0:
            _, chunk = win32file.ReadFile(self.handle, min(65536, remaining))
            if not chunk:
                raise ConnectionError("Incomplete response from CE pipe.")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def send_command(self, method, params=None):
        max_retries = 2
        last_error = None

        for attempt in range(max_retries):
            if not self.handle and not self.connect():
                raise ConnectionError("Cheat Engine Bridge (v11/v99) is not running (Pipe not found).")

            request = {
                "jsonrpc": "2.0",
                "method": method,
                "params": params or {},
                "id": int(time.time() * 1000),
            }

            try:
                req_json = json.dumps(request).encode("utf-8")
                header = struct.pack("<I", len(req_json))

                win32file.WriteFile(self.handle, header)
                win32file.WriteFile(self.handle, req_json)

                resp_header = self._read_exact(4)
                resp_len = struct.unpack("<I", resp_header)[0]
                if resp_len > MAX_RESPONSE_SIZE:
                    self.close()
                    raise ConnectionError(f"Response too large: {resp_len} bytes")

                resp_body = self._read_exact(resp_len)
                try:
                    response = json.loads(resp_body.decode("utf-8"))
                except json.JSONDecodeError:
                    self.close()
                    last_error = ConnectionError("Invalid JSON received from CE")
                    continue

                if "error" in response:
                    return {"success": False, "error": str(response["error"])}
                if "result" in response:
                    return response["result"]
                return response

            except (pywintypes.error, ConnectionError) as exc:
                self.close()
                last_error = ConnectionError(f"Pipe communication failed: {exc}")
                if attempt < max_retries - 1:
                    continue

        if last_error:
            raise last_error
        raise ConnectionError("Unknown communication error")

    def close(self) -> None:
        if self.handle:
            try:
                win32file.CloseHandle(self.handle)
            except Exception:
                pass
            self.handle = None


mcp = FastMCP(MCP_SERVER_NAME)
ce_client = CEBridgeClient()
register_ce_tools(mcp, ce_client.send_command, format_result)


if __name__ == "__main__":
    try:
        debug_log("Starting FastMCP server (v11/v99 compatible)...")
        mcp.run()
    except Exception as exc:
        debug_log(f"Fatal Crash: {exc}")
        traceback.print_exc(file=sys.stderr)
