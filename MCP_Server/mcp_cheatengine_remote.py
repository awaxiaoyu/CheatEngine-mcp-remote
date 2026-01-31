#!/usr/bin/env python3
"""
Cheat Engine MCP Bridge - 远程 TCP 版本
用于从另一台电脑通过网络连接到 Cheat Engine
"""

import sys
import os

# ============================================================================
# CRITICAL: WINDOWS LINE ENDING FIX FOR MCP (MONKEY-PATCH)
# ============================================================================

if sys.platform == "win32":
    import msvcrt
    from io import TextIOWrapper
    from contextlib import asynccontextmanager
    
    msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
    msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
    
    import mcp.server.stdio as mcp_stdio
    import anyio
    import anyio.lowlevel
    from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
    import mcp.types as types
    from mcp.shared.message import SessionMessage
    
    @asynccontextmanager
    async def _patched_stdio_server(
        stdin: "anyio.AsyncFile[str] | None" = None,
        stdout: "anyio.AsyncFile[str] | None" = None,
    ):
        if not stdin:
            stdin = anyio.wrap_file(TextIOWrapper(sys.stdin.buffer, encoding="utf-8", newline='\n'))
        if not stdout:
            stdout = anyio.wrap_file(TextIOWrapper(sys.stdout.buffer, encoding="utf-8", newline='\n'))

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
                        session_message = SessionMessage(message)
                        await read_stream_writer.send(session_message)
            except anyio.ClosedResourceError:
                await anyio.lowlevel.checkpoint()

        async def stdout_writer():
            try:
                async with write_stream_reader:
                    async for session_message in write_stream_reader:
                        json = session_message.message.model_dump_json(by_alias=True, exclude_none=True)
                        await stdout.write(json + "\n")
                        await stdout.flush()
            except anyio.ClosedResourceError:
                await anyio.lowlevel.checkpoint()

        async with anyio.create_task_group() as tg:
            tg.start_soon(stdin_reader)
            tg.start_soon(stdout_writer)
            yield read_stream, write_stream
    
    mcp_stdio.stdio_server = _patched_stdio_server

_mcp_stdout = sys.stdout
sys.stdout = sys.stderr

import json
import struct
import time
import traceback
import socket

try:
    from mcp.server.fastmcp import FastMCP
    
    if sys.platform == "win32":
        import mcp.server.fastmcp.server as fastmcp_server
        fastmcp_server.stdio_server = _patched_stdio_server
        
except ImportError as e:
    print(f"[MCP CE Remote] Import Error: {e}", file=sys.stderr, flush=True)
    sys.exit(1)

sys.stdout = _mcp_stdout

def debug_log(msg):
    print(f"[MCP CE Remote] {msg}", file=sys.stderr, flush=True)

def format_result(result):
    if isinstance(result, dict):
        return json.dumps(result, indent=None, ensure_ascii=False)
    elif isinstance(result, str):
        return result
    else:
        return json.dumps(result)

# ============================================================================
# 配置 - 通过环境变量设置远程 CE 服务器地址
# ============================================================================

# 从环境变量读取配置，默认为本地
CE_REMOTE_HOST = os.environ.get("CE_REMOTE_HOST", "127.0.0.1")
CE_REMOTE_PORT = int(os.environ.get("CE_REMOTE_PORT", "17171"))
MCP_SERVER_NAME = "cheatengine"

# ============================================================================
# TCP CLIENT
# ============================================================================

class CERemoteClient:
    """通过网络 TCP 连接到远程 Cheat Engine Bridge"""
    
    def __init__(self, host=None, port=None):
        self.host = host or CE_REMOTE_HOST
        self.port = port or CE_REMOTE_PORT
        self.socket = None

    def connect(self):
        """连接到远程 TCP Bridge"""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(30)  # 30秒超时
            self.socket.connect((self.host, self.port))
            debug_log(f"已连接到远程 CE: {self.host}:{self.port}")
            return True
        except socket.error as e:
            debug_log(f"连接失败: {e}")
            return False

    def send_command(self, method, params=None):
        """发送命令到远程 CE Bridge"""
        max_retries = 2
        last_error = None
        
        for attempt in range(max_retries):
            if not self.socket:
                if not self.connect():
                    raise ConnectionError(
                        f"无法连接到远程 Cheat Engine ({self.host}:{self.port}). "
                        "请确保远程 TCP Bridge 服务器正在运行。"
                    )

            request = {
                "jsonrpc": "2.0",
                "method": method,
                "params": params or {},
                "id": int(time.time() * 1000)
            }
            
            try:
                req_json = json.dumps(request).encode('utf-8')
                header = struct.pack('<I', len(req_json))
                
                self.socket.sendall(header + req_json)
                
                # 读取响应头
                resp_header = self.socket.recv(4)
                if len(resp_header) < 4:
                    self.close()
                    last_error = ConnectionError("响应头不完整")
                    continue
                    
                resp_len = struct.unpack('<I', resp_header)[0]
                
                if resp_len > 16 * 1024 * 1024: 
                    self.close()
                    raise ConnectionError(f"响应太大: {resp_len} 字节")

                # 读取响应体
                resp_body = b""
                while len(resp_body) < resp_len:
                    chunk = self.socket.recv(resp_len - len(resp_body))
                    if not chunk:
                        break
                    resp_body += chunk
                
                if len(resp_body) < resp_len:
                    self.close()
                    last_error = ConnectionError("响应体不完整")
                    continue
                
                try:
                    response = json.loads(resp_body.decode('utf-8'))
                except json.JSONDecodeError:
                    self.close()
                    last_error = ConnectionError("无效的 JSON 响应")
                    continue
                
                if 'error' in response:
                    return {"success": False, "error": str(response['error'])}
                if 'result' in response:
                    return response['result']
                    
                return response

            except socket.error as e:
                self.close()
                last_error = ConnectionError(f"通信失败: {e}")
                if attempt < max_retries - 1:
                    continue
        
        if last_error:
            raise last_error
        raise ConnectionError("未知通信错误")

    def close(self):
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
            self.socket = None


# ============================================================================
# MCP SERVER SETUP
# ============================================================================

mcp = FastMCP(MCP_SERVER_NAME)
ce_client = CERemoteClient()

# ============================================================================
# TOOLS - 与原版相同
# ============================================================================

@mcp.tool()
def ping() -> str:
    """Ping the Cheat Engine Bridge to verify connectivity."""
    try:
        result = ce_client.send_command("ping")
        return format_result(result)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})

@mcp.tool()
def get_version() -> str:
    """Get the Cheat Engine MCP Bridge version."""
    try:
        result = ce_client.send_command("get_version")
        return format_result(result)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})

@mcp.tool()
def get_process_info() -> str:
    """Get information about the currently attached process."""
    try:
        result = ce_client.send_command("get_process_info")
        return format_result(result)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})

@mcp.tool()
def list_processes() -> str:
    """List all running processes."""
    try:
        result = ce_client.send_command("list_processes")
        return format_result(result)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})

@mcp.tool()
def attach_process(pid: int) -> str:
    """Attach to a process by PID."""
    try:
        result = ce_client.send_command("attach_process", {"pid": pid})
        return format_result(result)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})

@mcp.tool()
def read_memory(address: str, size: int = 16) -> str:
    """Read memory at the specified address."""
    try:
        result = ce_client.send_command("read_memory", {
            "address": address,
            "size": size
        })
        return format_result(result)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})

@mcp.tool()
def read_integer(address: str, type_size: int = 4, signed: bool = False) -> str:
    """Read an integer value from memory."""
    try:
        result = ce_client.send_command("read_integer", {
            "address": address,
            "type_size": type_size,
            "signed": signed
        })
        return format_result(result)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})

@mcp.tool()
def read_string(address: str, max_length: int = 256, encoding: str = "utf-8") -> str:
    """Read a string from memory."""
    try:
        result = ce_client.send_command("read_string", {
            "address": address,
            "max_length": max_length,
            "encoding": encoding
        })
        return format_result(result)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})

@mcp.tool()
def read_pointer_chain(base_address: str, offsets: list) -> str:
    """Follow a pointer chain and read the final address."""
    try:
        result = ce_client.send_command("read_pointer_chain", {
            "base_address": base_address,
            "offsets": offsets
        })
        return format_result(result)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})

@mcp.tool()
def scan_all(value: str, value_type: str = "4bytes") -> str:
    """Scan for a value in memory."""
    try:
        result = ce_client.send_command("scan_all", {
            "value": value,
            "value_type": value_type
        })
        return format_result(result)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})

@mcp.tool()
def aob_scan(pattern: str) -> str:
    """Scan for an Array of Bytes pattern."""
    try:
        result = ce_client.send_command("aob_scan", {"pattern": pattern})
        return format_result(result)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})

@mcp.tool()
def disassemble(address: str, count: int = 10) -> str:
    """Disassemble instructions at the specified address."""
    try:
        result = ce_client.send_command("disassemble", {
            "address": address,
            "count": count
        })
        return format_result(result)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})

@mcp.tool()
def analyze_function(address: str) -> str:
    """Analyze a function at the specified address."""
    try:
        result = ce_client.send_command("analyze_function", {"address": address})
        return format_result(result)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})

@mcp.tool()
def get_rtti_classname(address: str) -> str:
    """Get the RTTI class name at the specified address."""
    try:
        result = ce_client.send_command("get_rtti_classname", {"address": address})
        return format_result(result)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})

@mcp.tool()
def dissect_structure(address: str, size: int = 256) -> str:
    """Auto-analyze a structure at the specified address."""
    try:
        result = ce_client.send_command("dissect_structure", {
            "address": address,
            "size": size
        })
        return format_result(result)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})

@mcp.tool()
def find_references(address: str) -> str:
    """Find references to the specified address."""
    try:
        result = ce_client.send_command("find_references", {"address": address})
        return format_result(result)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})

@mcp.tool()
def set_breakpoint(address: str) -> str:
    """Set a breakpoint at the specified address."""
    try:
        result = ce_client.send_command("set_breakpoint", {"address": address})
        return format_result(result)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})

@mcp.tool()
def remove_breakpoint(address: str) -> str:
    """Remove a breakpoint at the specified address."""
    try:
        result = ce_client.send_command("remove_breakpoint", {"address": address})
        return format_result(result)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})

@mcp.tool()
def get_breakpoint_hits() -> str:
    """Get all breakpoint hits since last check."""
    try:
        result = ce_client.send_command("get_breakpoint_hits")
        return format_result(result)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})

@mcp.tool()
def get_module_base(module_name: str) -> str:
    """Get the base address of a module."""
    try:
        result = ce_client.send_command("get_module_base", {"module_name": module_name})
        return format_result(result)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})

@mcp.tool()
def write_memory(address: str, data: str, data_type: str = "bytes") -> str:
    """Write data to memory."""
    try:
        result = ce_client.send_command("write_memory", {
            "address": address,
            "data": data,
            "data_type": data_type
        })
        return format_result(result)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})

# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    debug_log(f"启动远程 Cheat Engine MCP Bridge")
    debug_log(f"目标服务器: {CE_REMOTE_HOST}:{CE_REMOTE_PORT}")
    debug_log("=" * 60)
    mcp.run()
