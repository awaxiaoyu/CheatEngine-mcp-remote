#!/usr/bin/env python3
"""
Cheat Engine MCP TCP Bridge Server
运行在运行 Cheat Engine 的电脑上
将本地 Named Pipe 桥接到 TCP 网络连接

修复历史:
  [FIX-1] Pipe 句柄泄露: 原版 finally 块只关闭 client_socket，未关闭 pipe_handle
          → 导致 ERROR_PIPE_BUSY (231)，后续所有连接失败
  [FIX-2] 连接序列化: 增加 pipe_lock 全局锁，防止多个线程竞争单实例 Pipe
  [FIX-3] Pipe 重试: connect_to_ce_pipe 增加 WaitNamedPipe + 最多 5 次重试
  [FIX-4] 安全读取: ReadFile 分块读取 + 空数据检测，防止大响应或断管死循环
  [FIX-5] 释放间隔: Pipe 关闭后 sleep(0.1) 等 CE Lua 重新 ConnectNamedPipe
"""

import socket
import struct
import threading
import sys
import time

try:
    import win32file
    import win32pipe
    import pywintypes
except ImportError:
    print("[错误] 需要安装 pywin32: pip install pywin32")
    sys.exit(1)

# 配置
PIPE_NAME = r"\\.\pipe\CE_MCP_Bridge_v99"
TCP_HOST = "0.0.0.0"
TCP_PORT = 17171

# [FIX-2] 全局 Pipe 锁: CE Lua Pipe 是单实例，同一时间只能有一个客户端连接
# 所有线程必须通过此锁序列化对 Pipe 的访问
pipe_lock = threading.Lock()


def connect_to_ce_pipe(max_retries=5, retry_delay=0.3):
    """
    连接到 Cheat Engine 的 Named Pipe

    [FIX-3] 增加重试逻辑:
    - WaitNamedPipe: 等待 Pipe 变为可用状态（最多 2 秒）
    - ERROR_PIPE_BUSY (231) 时自动重试，最多 max_retries 次
    - 每次重试间隔 retry_delay 秒
    """
    for attempt in range(max_retries):
        try:
            # [FIX-3] 等待 Pipe 可用（CE Lua 可能还没来得及重新 ConnectNamedPipe）
            try:
                win32pipe.WaitNamedPipe(PIPE_NAME, 2000)
            except pywintypes.error:
                pass  # Pipe 不存在或超时，仍然尝试 CreateFile

            handle = win32file.CreateFile(
                PIPE_NAME,
                win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                0,
                None,
                win32file.OPEN_EXISTING,
                0,
                None
            )
            return handle
        except pywintypes.error as e:
            error_code = e.args[0] if e.args else 0
            # [FIX-3] ERROR_PIPE_BUSY: 上一个连接的 Pipe 句柄刚释放，CE Lua 还没重新监听
            if error_code == 231 and attempt < max_retries - 1:
                print(f"[重试] Pipe 繁忙，{retry_delay}s 后重试 ({attempt+1}/{max_retries})...")
                time.sleep(retry_delay)
                continue
            print(f"[错误] 无法连接到 Cheat Engine: {e}")
            print("[提示] 请确保 Cheat Engine 已启动并加载了 ce_mcp_bridge.lua")
            return None
    return None


def close_pipe_handle(pipe_handle):
    """
    [FIX-1] 安全关闭 Pipe 句柄

    原版 bug: pipe_handle 在 finally 中从未被关闭
    → Pipe 实例永远被占用 → 后续 CreateFile 返回 ERROR_PIPE_BUSY
    """
    if pipe_handle is not None:
        try:
            win32file.CloseHandle(pipe_handle)
        except Exception:
            pass


def handle_single_request(pipe_handle, client_socket):
    """
    处理单个请求-响应周期

    协议: [4字节长度头][消息体] 双向对称
    返回 False 表示连接应关闭（TCP 断开或协议错误）
    """
    # 读取 TCP 请求头（4 字节，小端 uint32 长度）
    header = b""
    while len(header) < 4:
        chunk = client_socket.recv(4 - len(header))
        if not chunk:
            return False  # TCP 客户端已断开
        header += chunk

    msg_len = struct.unpack('<I', header)[0]

    if msg_len > 16 * 1024 * 1024:  # 16MB 安全限制
        print(f"[错误] 消息太大: {msg_len} 字节")
        return False

    # 读取 TCP 请求体
    data = b""
    while len(data) < msg_len:
        chunk = client_socket.recv(min(65536, msg_len - len(data)))
        if not chunk:
            return False
        data += chunk

    if len(data) < msg_len:
        return False

    # 转发到 Named Pipe: 先写长度头，再写消息体
    win32file.WriteFile(pipe_handle, header)
    win32file.WriteFile(pipe_handle, data)

    # 从 Named Pipe 读取响应头
    resp_header = win32file.ReadFile(pipe_handle, 4)[1]
    if len(resp_header) < 4:
        return False

    resp_len = struct.unpack('<I', resp_header)[0]

    if resp_len > 16 * 1024 * 1024:
        print(f"[错误] 响应太大: {resp_len} 字节")
        return False

    # [FIX-4] 分块读取响应体，防止大响应一次读取失败或 Pipe 缓冲区不足
    # 原版: 单次 ReadFile(pipe_handle, resp_len)
    # 修复: 循环分块读取，每次最多 64KB，带空数据检测防死循环
    resp_body = b""
    remaining = resp_len
    while remaining > 0:
        read_size = min(65536, remaining)
        _, chunk = win32file.ReadFile(pipe_handle, read_size)
        # [FIX-4] 空数据检测: Pipe 断开时 ReadFile 可能返回空而不抛异常
        if not chunk:
            raise ConnectionError("Pipe 返回空数据")
        resp_body += chunk
        remaining -= len(chunk)

    # 转发完整响应回 TCP 客户端
    client_socket.sendall(resp_header + resp_body)
    return True


def pipe_client_thread(client_socket, client_addr):
    """
    处理单个 TCP 客户端连接

    流程: 获取锁 → 连接 Pipe → 请求/响应循环 → 关闭 Pipe → 释放锁

    [FIX-2] pipe_lock 确保:
    - 同一时间只有一个线程持有 Pipe 连接
    - 避免多个线程竞争单实例 Named Pipe
    - 后续线程在 lock.acquire() 处排队等待
    """
    pipe_handle = None
    try:
        # [FIX-2] 获取全局锁，序列化 Pipe 访问
        with pipe_lock:
            pipe_handle = connect_to_ce_pipe()
            if not pipe_handle:
                print(f"[跳过] 无法为 {client_addr} 建立 Pipe 连接")
                return  # → 外层 finally 关闭 socket

            try:
                # 请求/响应循环: MCP 客户端可能在一个 TCP 连接中发送多个请求
                while True:
                    if not handle_single_request(pipe_handle, client_socket):
                        break
            except ConnectionResetError:
                print(f"[断开] 客户端 {client_addr} 连接重置")
            except pywintypes.error as e:
                print(f"[错误] Pipe 通信失败 ({client_addr}): {e}")
            except Exception as e:
                print(f"[错误] 客户端 {client_addr}: {e}")
            finally:
                # [FIX-1] ★ 关键修复: 关闭 Pipe 句柄释放 Named Pipe 实例
                # 原版 bug: 此处缺少 CloseHandle → Pipe 永久被占用
                close_pipe_handle(pipe_handle)
                pipe_handle = None  # 防止外层 finally 重复关闭

                # [FIX-5] 等待 CE Lua 脚本重新调用 ConnectNamedPipe()
                # 没有这个间隔，下一个 CreateFile 可能因为 Lua 还没准备好而失败
                time.sleep(0.1)

        # pipe_lock 在 with 块退出时自动释放

    finally:
        # 双重保险: 如果 connect_to_ce_pipe 异常导致 pipe_handle 未被内层 finally 处理
        if pipe_handle is not None:
            close_pipe_handle(pipe_handle)
        try:
            client_socket.close()
        except Exception:
            pass
        print(f"[断开] 客户端 {client_addr} 已断开（Pipe 已释放）")


def main():
    print("=" * 60)
    print("Cheat Engine MCP TCP Bridge Server (Fixed)")
    print("=" * 60)
    print(f"监听端口: {TCP_PORT}")
    print(f"目标 Pipe: {PIPE_NAME}")
    print("=" * 60)

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        server.bind((TCP_HOST, TCP_PORT))
        server.listen(5)
        print(f"[启动] TCP 服务器已启动，等待连接...")
    except Exception as e:
        print(f"[错误] 无法启动服务器: {e}")
        sys.exit(1)

    try:
        while True:
            client_sock, client_addr = server.accept()
            print(f"[接入] 新客户端 {client_addr}")

            # 每个 TCP 连接在独立线程中处理
            # daemon=True: 主线程退出时自动终止所有客户端线程
            client_thread = threading.Thread(
                target=pipe_client_thread,
                args=(client_sock, client_addr),
                daemon=True
            )
            client_thread.start()

    except KeyboardInterrupt:
        print("\n[关闭] 服务器正在关闭...")
    finally:
        server.close()


if __name__ == "__main__":
    main()
