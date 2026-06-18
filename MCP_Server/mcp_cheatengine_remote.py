#!/usr/bin/env python3
"""Cheat Engine MCP Bridge - remote TCP client."""

import json
import os
import socket
import struct
import sys
import time

from ce_tool_specs import register_ce_tools
from mcp_stdio_compat import patch_stdio_for_windows


_patched_stdio_server = patch_stdio_for_windows()

_mcp_stdout = sys.stdout
sys.stdout = sys.stderr
try:
    from mcp.server.fastmcp import FastMCP

    if _patched_stdio_server is not None:
        import mcp.server.fastmcp.server as fastmcp_server

        fastmcp_server.stdio_server = _patched_stdio_server
except ImportError as exc:
    print(f"[MCP CE Remote] Import Error: {exc}", file=sys.stderr, flush=True)
    sys.exit(1)
finally:
    sys.stdout = _mcp_stdout


CE_REMOTE_HOST = os.environ.get("CE_REMOTE_HOST", "127.0.0.1")
CE_REMOTE_PORT = int(os.environ.get("CE_REMOTE_PORT", "17171"))
CE_BRIDGE_TOKEN = os.environ.get("CE_BRIDGE_TOKEN", "")
MCP_SERVER_NAME = "cheatengine"
MAX_RESPONSE_SIZE = 16 * 1024 * 1024
AUTH_METHOD = "__ce_bridge_auth"


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError:
        return default


CE_TCP_TIMEOUT = _float_env("CE_TCP_TIMEOUT", 30.0)


def debug_log(message: str) -> None:
    print(f"[MCP CE Remote] {message}", file=sys.stderr, flush=True)


def format_result(result):
    if isinstance(result, dict):
        return json.dumps(result, indent=None, ensure_ascii=False)
    if isinstance(result, str):
        return result
    return json.dumps(result, ensure_ascii=False)


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    chunks = []
    remaining = size
    while remaining > 0:
        try:
            chunk = sock.recv(min(65536, remaining))
        except socket.timeout as exc:
            raise TimeoutError(f"Timed out while reading {size} bytes") from exc
        if not chunk:
            raise ConnectionError("Connection closed before the full frame was received")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _send_framed_json(sock: socket.socket, message: dict) -> None:
    payload = json.dumps(message).encode("utf-8")
    sock.sendall(struct.pack("<I", len(payload)) + payload)


def _read_framed_json(sock: socket.socket) -> dict:
    resp_header = _recv_exact(sock, 4)
    resp_len = struct.unpack("<I", resp_header)[0]
    if resp_len > MAX_RESPONSE_SIZE:
        raise ConnectionError(f"Response too large: {resp_len} bytes")
    resp_body = _recv_exact(sock, resp_len)
    try:
        return json.loads(resp_body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ConnectionError("Invalid JSON response") from exc


class CERemoteClient:
    """TCP client for a remote Cheat Engine bridge."""

    def __init__(self, host=None, port=None, token=None, timeout=None):
        self.host = host or CE_REMOTE_HOST
        self.port = port or CE_REMOTE_PORT
        self.token = CE_BRIDGE_TOKEN if token is None else token
        self.timeout = CE_TCP_TIMEOUT if timeout is None else timeout
        self.socket = None

    def connect(self) -> bool:
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(self.timeout)
            self.socket.connect((self.host, self.port))
            if self.token:
                self._authenticate()
            debug_log(f"已连接到远程 CE: {self.host}:{self.port}")
            return True
        except (socket.error, TimeoutError, ConnectionError, ValueError) as exc:
            debug_log(f"连接失败: {exc}")
            self.close()
            return False

    def _authenticate(self) -> None:
        request = {
            "jsonrpc": "2.0",
            "method": AUTH_METHOD,
            "params": {"token": self.token},
            "id": "auth",
        }
        _send_framed_json(self.socket, request)
        response = _read_framed_json(self.socket)
        result = response.get("result", {})
        if "error" in response or not result.get("success"):
            raise ConnectionError("Remote bridge authentication failed")

    def send_command(self, method, params=None):
        max_retries = 2
        last_error = None

        for attempt in range(max_retries):
            if not self.socket and not self.connect():
                raise ConnectionError(
                    f"无法连接到远程 Cheat Engine ({self.host}:{self.port}). "
                    "请确保远程 TCP Bridge 服务器正在运行。"
                )

            request = {
                "jsonrpc": "2.0",
                "method": method,
                "params": params or {},
                "id": int(time.time() * 1000),
            }

            try:
                _send_framed_json(self.socket, request)
                response = _read_framed_json(self.socket)
                if "error" in response:
                    return {"success": False, "error": str(response["error"])}
                if "result" in response:
                    return response["result"]
                return response

            except (socket.error, TimeoutError, ConnectionError) as exc:
                self.close()
                last_error = ConnectionError(f"通信失败: {exc}")
                if attempt < max_retries - 1:
                    continue

        if last_error:
            raise last_error
        raise ConnectionError("未知通信错误")

    def close(self) -> None:
        if self.socket:
            try:
                self.socket.close()
            except Exception:
                pass
            self.socket = None


mcp = FastMCP(MCP_SERVER_NAME)
ce_client = CERemoteClient()
register_ce_tools(mcp, ce_client.send_command, format_result)


if __name__ == "__main__":
    debug_log("启动远程 Cheat Engine MCP Bridge")
    debug_log(f"目标服务器: {CE_REMOTE_HOST}:{CE_REMOTE_PORT}")
    debug_log(f"TCP 超时: {CE_TCP_TIMEOUT:g}s")
    if CE_BRIDGE_TOKEN:
        debug_log("已启用 CE_BRIDGE_TOKEN 认证")
    else:
        debug_log("未设置 CE_BRIDGE_TOKEN；远程连接保持兼容模式（无认证）")
    debug_log("=" * 60)
    mcp.run()
