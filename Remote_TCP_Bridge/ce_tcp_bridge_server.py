#!/usr/bin/env python3
"""Cheat Engine MCP TCP Bridge Server.

Runs on the machine that hosts Cheat Engine. It forwards length-prefixed JSON-RPC
frames between TCP clients and the local CE named pipe.
"""

import hmac
import json
import os
import socket
import struct
import sys
import threading
import time

try:
    import pywintypes
    import win32file
    import win32pipe
except ImportError:
    print("[错误] 需要安装 pywin32: pip install pywin32")
    sys.exit(1)


PIPE_NAME = r"\\.\pipe\CE_MCP_Bridge_v99"
TCP_HOST = os.environ.get("CE_TCP_HOST", "0.0.0.0")
TCP_PORT = int(os.environ.get("CE_REMOTE_PORT", os.environ.get("CE_TCP_PORT", "17171")))
CE_BRIDGE_TOKEN = os.environ.get("CE_BRIDGE_TOKEN", "")
AUTH_METHOD = "__ce_bridge_auth"
STATUS_METHOD = "__ce_bridge_status"
MAX_MESSAGE_SIZE = 16 * 1024 * 1024
SERVER_STARTED_AT = time.time()


def _float_env(name, default):
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError:
        return default


CE_TCP_TIMEOUT = _float_env("CE_TCP_TIMEOUT", 30.0)
PIPE_HOLD_TIMEOUT = _float_env("CE_PIPE_HOLD_TIMEOUT", max(120.0, CE_TCP_TIMEOUT))

# CE Lua pipe is single-instance; access must be serialized.
pipe_lock = threading.Lock()
client_count_lock = threading.Lock()
active_client_count = 0


def recv_exact(sock, size):
    chunks = []
    remaining = size
    while remaining > 0:
        try:
            chunk = sock.recv(min(65536, remaining))
        except socket.timeout as exc:
            raise TimeoutError(f"读取 {size} 字节超时") from exc
        if not chunk:
            raise ConnectionError("连接在帧读取完成前关闭")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_framed_message(sock, max_size=MAX_MESSAGE_SIZE):
    header = recv_exact(sock, 4)
    msg_len = struct.unpack("<I", header)[0]
    if msg_len > max_size:
        raise ValueError(f"消息太大: {msg_len} 字节")
    body = recv_exact(sock, msg_len)
    return header, body


def read_frame_from_bytes(data):
    if len(data) < 4:
        raise ConnectionError("帧头不完整")
    header = data[:4]
    msg_len = struct.unpack("<I", header)[0]
    body = data[4:4 + msg_len]
    if len(body) != msg_len:
        raise ConnectionError("帧体不完整")
    return header, body


def send_framed_json(sock, message):
    payload = json.dumps(message).encode("utf-8")
    sock.sendall(struct.pack("<I", len(payload)) + payload)


def build_transport_status():
    with client_count_lock:
        clients = active_client_count
    return {
        "success": True,
        "uptime_seconds": int(time.time() - SERVER_STARTED_AT),
        "auth_enabled": bool(CE_BRIDGE_TOKEN),
        "tcp_timeout": CE_TCP_TIMEOUT,
        "pipe_hold_timeout": PIPE_HOLD_TIMEOUT,
        "active_client_count": clients,
        "listening_host": TCP_HOST,
        "listening_port": TCP_PORT,
        "max_message_size": MAX_MESSAGE_SIZE,
    }


def read_client_request_frame(client_socket):
    header, body = read_framed_message(client_socket)
    return header, body


def handle_internal_request(client_socket):
    header, body = read_client_request_frame(client_socket)
    try:
        request = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        return False, (header, body)

    if request.get("method") != STATUS_METHOD:
        return False, (header, body)

    send_framed_json(
        client_socket,
        {"jsonrpc": "2.0", "result": build_transport_status(), "id": request.get("id")},
    )
    return True, None


def authenticate_client(client_socket, expected_token=CE_BRIDGE_TOKEN):
    """Optional first-frame authentication.

    Compatibility mode: when expected_token is empty, no frame is consumed.
    Secure mode: the first frame must be AUTH_METHOD with matching token.
    """
    if not expected_token:
        return True

    try:
        _, body = read_framed_message(client_socket)
        request = json.loads(body.decode("utf-8"))
    except Exception as exc:
        send_framed_json(
            client_socket,
            {"jsonrpc": "2.0", "error": {"code": -32001, "message": f"Auth parse failed: {exc}"}, "id": "auth"},
        )
        return False

    request_id = request.get("id", "auth")
    token = request.get("params", {}).get("token", "")
    ok = request.get("method") == AUTH_METHOD and hmac.compare_digest(str(token), str(expected_token))

    if ok:
        send_framed_json(
            client_socket,
            {"jsonrpc": "2.0", "result": {"success": True}, "id": request_id},
        )
        return True

    send_framed_json(
        client_socket,
        {"jsonrpc": "2.0", "error": {"code": -32000, "message": "Authentication failed"}, "id": request_id},
    )
    return False


def connect_to_ce_pipe(max_retries=5, retry_delay=0.3):
    for attempt in range(max_retries):
        try:
            try:
                win32pipe.WaitNamedPipe(PIPE_NAME, 2000)
            except pywintypes.error:
                pass

            return win32file.CreateFile(
                PIPE_NAME,
                win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                0,
                None,
                win32file.OPEN_EXISTING,
                0,
                None,
            )
        except pywintypes.error as exc:
            error_code = exc.args[0] if exc.args else 0
            if error_code == 231 and attempt < max_retries - 1:
                print(f"[重试] Pipe 繁忙，{retry_delay}s 后重试 ({attempt + 1}/{max_retries})...")
                time.sleep(retry_delay)
                continue
            print(f"[错误] 无法连接到 Cheat Engine: {exc}")
            print("[提示] 请确认 Cheat Engine 已启动并加载 ce_mcp_bridge.lua")
            return None
    return None


def close_pipe_handle(pipe_handle):
    if pipe_handle is not None:
        try:
            win32file.CloseHandle(pipe_handle)
        except Exception:
            pass


def read_pipe_exact(pipe_handle, size):
    chunks = []
    remaining = size
    while remaining > 0:
        _, chunk = win32file.ReadFile(pipe_handle, min(65536, remaining))
        if not chunk:
            raise ConnectionError("Pipe 返回空数据")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def handle_single_request(pipe_handle, client_socket, first_frame=None):
    if first_frame is None:
        header, data = read_framed_message(client_socket)
    else:
        header, data = first_frame

    win32file.WriteFile(pipe_handle, header)
    win32file.WriteFile(pipe_handle, data)

    resp_header = read_pipe_exact(pipe_handle, 4)
    resp_len = struct.unpack("<I", resp_header)[0]
    if resp_len > MAX_MESSAGE_SIZE:
        raise ValueError(f"响应太大: {resp_len} 字节")

    resp_body = read_pipe_exact(pipe_handle, resp_len)
    client_socket.sendall(resp_header + resp_body)
    return True


def pipe_client_thread(client_socket, client_addr):
    global active_client_count
    pipe_handle = None
    try:
        with client_count_lock:
            active_client_count += 1
        client_socket.settimeout(CE_TCP_TIMEOUT)
        if not authenticate_client(client_socket):
            print(f"[拒绝] 客户端 {client_addr} 认证失败")
            return

        handled, first_frame = handle_internal_request(client_socket)
        if handled:
            return

        with pipe_lock:
            pipe_handle = connect_to_ce_pipe()
            if not pipe_handle:
                print(f"[跳过] 无法为 {client_addr} 建立 Pipe 连接")
                return

            deadline = time.monotonic() + PIPE_HOLD_TIMEOUT
            try:
                while time.monotonic() < deadline:
                    handle_single_request(pipe_handle, client_socket, first_frame)
                    first_frame = None
                print(f"[超时] 客户端 {client_addr} 持有 Pipe 超过 {PIPE_HOLD_TIMEOUT:g}s，关闭连接")
            except (ConnectionError, ConnectionResetError):
                print(f"[断开] 客户端 {client_addr} 已断开")
            except TimeoutError:
                print(f"[超时] 客户端 {client_addr} 在 {CE_TCP_TIMEOUT:g}s 内无完整请求")
            except pywintypes.error as exc:
                print(f"[错误] Pipe 通信失败 ({client_addr}): {exc}")
            except Exception as exc:
                print(f"[错误] 客户端 {client_addr}: {exc}")
            finally:
                close_pipe_handle(pipe_handle)
                pipe_handle = None
                time.sleep(0.1)
    finally:
        with client_count_lock:
            active_client_count = max(0, active_client_count - 1)
        if pipe_handle is not None:
            close_pipe_handle(pipe_handle)
        try:
            client_socket.close()
        except Exception:
            pass
        print(f"[断开] 客户端 {client_addr} 已断开（Pipe 已释放）")


def main():
    print("=" * 60)
    print("Cheat Engine MCP TCP Bridge Server")
    print("=" * 60)
    print(f"监听地址: {TCP_HOST}:{TCP_PORT}")
    print(f"目标 Pipe: {PIPE_NAME}")
    print(f"TCP 超时: {CE_TCP_TIMEOUT:g}s")
    print(f"Pipe 持有上限: {PIPE_HOLD_TIMEOUT:g}s")
    if CE_BRIDGE_TOKEN:
        print("[安全] 已启用 CE_BRIDGE_TOKEN 认证")
    else:
        print("[警告] 未设置 CE_BRIDGE_TOKEN，当前为兼容模式（无认证）")
    print("=" * 60)

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        server.bind((TCP_HOST, TCP_PORT))
        server.listen(5)
        print("[启动] TCP 服务器已启动，等待连接...")
    except Exception as exc:
        print(f"[错误] 无法启动服务器: {exc}")
        sys.exit(1)

    try:
        while True:
            client_sock, client_addr = server.accept()
            print(f"[接入] 新客户端 {client_addr}")
            client_thread = threading.Thread(
                target=pipe_client_thread,
                args=(client_sock, client_addr),
                daemon=True,
            )
            client_thread.start()
    except KeyboardInterrupt:
        print("\n[关闭] 服务器正在关闭...")
    finally:
        server.close()


if __name__ == "__main__":
    main()
