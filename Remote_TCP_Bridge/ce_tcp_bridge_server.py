#!/usr/bin/env python3
"""
Cheat Engine MCP TCP Bridge Server
运行在运行 Cheat Engine 的电脑上
将本地 Named Pipe 桥接到 TCP 网络连接
"""

import socket
import struct
import json
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
TCP_HOST = "0.0.0.0"  # 监听所有网络接口
TCP_PORT = 17171      # 默认端口


def connect_to_ce_pipe():
    """连接到 Cheat Engine 的 Named Pipe"""
    try:
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
        print(f"[错误] 无法连接到 Cheat Engine: {e}")
        print("[提示] 请确保 Cheat Engine 已启动并加载了 ce_mcp_bridge.lua")
        return None


def pipe_client_thread(pipe_handle, client_socket, client_addr):
    """处理单个客户端连接"""
    print(f"[连接] 客户端 {client_addr} 已连接")
    
    try:
        while True:
            # 从 TCP 客户端读取数据
            # 先读取 4 字节的长度头
            header = client_socket.recv(4)
            if not header or len(header) < 4:
                break
            
            msg_len = struct.unpack('<I', header)[0]
            
            if msg_len > 16 * 1024 * 1024:  # 16MB 限制
                print(f"[错误] 消息太大: {msg_len} 字节")
                break
            
            # 读取消息体
            data = b""
            while len(data) < msg_len:
                chunk = client_socket.recv(msg_len - len(data))
                if not chunk:
                    break
                data += chunk
            
            if len(data) < msg_len:
                break
            
            # 转发到 Named Pipe
            try:
                win32file.WriteFile(pipe_handle, header)
                win32file.WriteFile(pipe_handle, data)
            except pywintypes.error as e:
                print(f"[错误] 写入 Pipe 失败: {e}")
                break
            
            # 从 Named Pipe 读取响应
            try:
                resp_header = win32file.ReadFile(pipe_handle, 4)[1]
                if len(resp_header) < 4:
                    break
                
                resp_len = struct.unpack('<I', resp_header)[0]
                
                if resp_len > 16 * 1024 * 1024:
                    print(f"[错误] 响应太大: {resp_len} 字节")
                    break
                
                resp_body = win32file.ReadFile(pipe_handle, resp_len)[1]
                
                # 转发回 TCP 客户端
                client_socket.sendall(resp_header + resp_body)
                
            except pywintypes.error as e:
                print(f"[错误] 读取 Pipe 失败: {e}")
                break
                
    except ConnectionResetError:
        print(f"[断开] 客户端 {client_addr} 连接重置")
    except Exception as e:
        print(f"[错误] 客户端 {client_addr}: {e}")
    finally:
        client_socket.close()
        print(f"[断开] 客户端 {client_addr} 已断开")


def main():
    print("=" * 60)
    print("Cheat Engine MCP TCP Bridge Server")
    print("=" * 60)
    print(f"监听端口: {TCP_PORT}")
    print(f"目标 Pipe: {PIPE_NAME}")
    print("=" * 60)
    
    # 创建 TCP 服务器
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
            
            # 为每个客户端连接到 Pipe
            pipe_handle = connect_to_ce_pipe()
            if not pipe_handle:
                client_sock.close()
                continue
            
            # 启动客户端处理线程
            client_thread = threading.Thread(
                target=pipe_client_thread,
                args=(pipe_handle, client_sock, client_addr),
                daemon=True
            )
            client_thread.start()
            
    except KeyboardInterrupt:
        print("\n[关闭] 服务器正在关闭...")
    finally:
        server.close()


if __name__ == "__main__":
    main()
