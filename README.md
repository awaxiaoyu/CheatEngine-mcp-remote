# Cheat Engine MCP Bridge - 远程版

**如果觉得好用就给个star吧，谢谢喵**

Connect Cursor, Copilot & Claude directly to Cheat Engine via MCP. **支持远程网络连接！**

在原版 [cheatengine-mcp-bridge](https://github.com/miscusi-peek/cheatengine-mcp-bridge) 基础上添加了 **TCP 远程连接支持**，让你可以在一台电脑上运行 AI 助手，远程控制另一台电脑上的 Cheat Engine。

---

## 新功能：远程连接

### 使用场景

- **笔记本 + 台式机**: 使用我的另一个项目：[CheatEngine-DMA](https://github.com/awaxiaoyu/CheatEngine-DMA)在轻薄本上运行DMA版本的 Cheat Engine，在台式机上用 Trae/Claude 远程控制轻薄本上运行的Cheat Engine
- **团队协作**: 多人共享一台强大的游戏电脑进行逆向分析
- **安全隔离**: 在虚拟机/沙盒中运行 Cheat Engine，通过远程连接操作

### 架构

```
┌─────────────────────────────────────────────────────────────────┐
│  你的电脑 (运行 Trae/Cursor)                                     │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  mcp_cheatengine_remote.py (TCP 客户端)                  │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
                              │ TCP (端口 17171)
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  游戏电脑 (运行 Cheat Engine)                                    │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  ce_tcp_bridge_server.py  (TCP 服务器)                   │    │
│  │  ┌─────────────────────────────────────────────────┐    │    │
│  │  │  Named Pipe: \\.\pipe\CE_MCP_Bridge_v99         │    │    │
│  │  └─────────────────────────────────────────────────┘    │    │
│  └─────────────────────────────────────────────────────────┘    │
│                              │                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  Cheat Engine + ce_mcp_bridge.lua                       │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

---

## 快速开始

### 本地模式（原版功能）

与原版相同，直接在运行 Cheat Engine 的电脑上使用：

```bash
# 安装依赖
pip install -r MCP_Server/requirements.txt

# 启动 Cheat Engine，加载 ce_mcp_bridge.lua
# 配置 MCP 使用 mcp_cheatengine_local.py
```

### 远程模式（新增功能）

#### 1. 在游戏电脑上（运行 Cheat Engine）

```bash
# 安装依赖
pip install pywin32

# 1. 启动 Cheat Engine
# 2. 加载 MCP_Server/ce_mcp_bridge.lua
# 3. 可选：启用 token 认证（服务端和客户端必须一致）
set CE_BRIDGE_TOKEN=change-me
set CE_TCP_TIMEOUT=30

# 4. 启动 TCP 桥接服务器
python Remote_TCP_Bridge/ce_tcp_bridge_server.py
```

#### 2. 在你的电脑上（运行 Trae）

```bash
# 安装依赖
pip install mcp

# 设置环境变量
set CE_REMOTE_HOST=192.168.1.100  # 游戏电脑IP
set CE_REMOTE_PORT=17171
set CE_BRIDGE_TOKEN=change-me     # 如服务端启用了 token，这里必须一致
set CE_TCP_TIMEOUT=30

# 配置 MCP 使用 MCP_Server/mcp_cheatengine_remote.py
```

---

## MCP 配置示例

### 本地模式

```json
{
  "mcpServers": {
    "cheatengine": {
      "command": "python",
      "args": ["C:/path/to/MCP_Server/mcp_cheatengine_local.py"]
    }
  }
}
```

### 远程模式

```json
{
  "mcpServers": {
    "cheatengine": {
      "command": "python",
      "args": ["C:/path/to/MCP_Server/mcp_cheatengine_remote.py"],
      "env": {
        "CE_REMOTE_HOST": "192.168.1.100",
        "CE_REMOTE_PORT": "17171",
        "CE_BRIDGE_TOKEN": "change-me",
        "CE_TCP_TIMEOUT": "30"
      }
    }
  }
}
```

---

## 文件说明

| 文件 | 用途 |
|------|------|
| `MCP_Server/mcp_cheatengine_local.py` | 本地模式 MCP 服务器（原版功能） |
| `MCP_Server/mcp_cheatengine_remote.py` | 远程模式 MCP 客户端（新增） |
| `MCP_Server/ce_tool_specs.py` | local/remote 共用 MCP 工具规格，避免协议漂移 |
| `MCP_Server/mcp_stdio_compat.py` | Windows MCP stdio 换行兼容补丁 |
| `MCP_Server/ce_mcp_bridge.lua` | Cheat Engine Lua 桥接脚本 |
| `Remote_TCP_Bridge/ce_tcp_bridge_server.py` | TCP 桥接服务器（运行在CE电脑） |
| `AI_Context/` | AI 上下文文档和命令参考 |

---

## 防火墙配置

在游戏电脑上允许端口 17171：

```powershell
# 以管理员身份运行
New-NetFirewallRule -DisplayName "CE MCP Bridge" -Direction Inbound -Protocol TCP -LocalPort 17171 -Action Allow
```

---

## 原版功能

本地模式和远程模式共用同一份工具规格，工具面保持一致：

- **内存操作**: 读取内存、整数、字符串、指针链扫描
- **代码分析**: 反汇编、函数分析、结构体解析、RTTI 类名识别
- **调试**: 硬件断点、数据断点、DBVM 隐形追踪
- **43+ 个 MCP 工具**

---

## 诊断与排障

### 本地模式

1. 先调用 `ping`，确认 MCP server 能连接 CE Named Pipe。
2. 再调用 `get_bridge_status`，查看 `process_attached`、`module_count`、`scan_active`、`breakpoint_count`、`active_dbvm_watch_count`。

### 远程模式

1. 先调用 `get_remote_transport_status`，确认 TCP bridge 本身在线、`auth_enabled` 是否符合预期、`active_client_count` 是否异常。
2. 再调用 `get_bridge_status`，确认远端 CE Lua bridge 已加载并能访问目标进程。

常见判断：

- **token mismatch**: `get_remote_transport_status` 连接失败或认证失败，检查两端 `CE_BRIDGE_TOKEN` 是否一致。
- **Pipe busy / CE 未加载 Lua**: transport 状态正常，但 `ping` 或 `get_bridge_status` 失败，检查 Cheat Engine 是否加载 `ce_mcp_bridge.lua`。
- **DBVM 未启用**: `get_bridge_status.capabilities.dbvm_available=false`，需要在 CE 设置里启用 DBVM/DBK 后再使用 DBVM 工具。
- **连接长期占用**: `active_client_count` 异常偏高或请求超时，检查是否有旧 MCP 客户端未退出。

---

## 安全提示

1. **兼容默认**: 未设置 `CE_BRIDGE_TOKEN` 时仍是无认证 TCP，方便旧配置继续使用，但只建议在可信局域网内使用。
2. **推荐启用 token**: 服务端和客户端都设置同一个 `CE_BRIDGE_TOKEN` 后，TCP 连接必须先完成认证握手。
3. **限制访问**: 在防火墙中限制只允许特定 IP 访问端口 `17171`。
4. **使用 SSH 隧道**: 如需跨公网连接，建议不要直接暴露端口；使用 SSH tunnel/VPN 后把客户端 `CE_REMOTE_HOST` 指向 tunnel 本地地址。
5. **超时控制**: `CE_TCP_TIMEOUT` 控制 socket idle/read 超时，默认 `30` 秒；服务端也会限制单个客户端长期占用 CE Pipe。

---

## 许可证

与原项目相同，遵循原项目的许可证。

---

## 致谢

基于 [miscusi-peek/cheatengine-mcp-bridge](https://github.com/miscusi-peek/cheatengine-mcp-bridge) 开发，感谢原作者的优秀工作！
