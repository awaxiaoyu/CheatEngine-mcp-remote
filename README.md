# Cheat Engine MCP Bridge - 远程版

Connect Cursor, Copilot & Claude directly to Cheat Engine via MCP. **支持远程网络连接！**

在原版 [cheatengine-mcp-bridge](https://github.com/miscusi-peek/cheatengine-mcp-bridge) 基础上添加了 **TCP 远程连接支持**，让你可以在一台电脑上运行 AI 助手，远程控制另一台电脑上的 Cheat Engine。

---

## 新功能：远程连接

### 使用场景

- **笔记本 + 台式机**: 在轻薄本上运行 Trae/Claude，远程控制台式机上的 Cheat Engine
- **团队协作**: 多人共享一台强大的游戏电脑进行逆向分析
- **安全隔离**: 在虚拟机/沙盒中运行 Cheat Engine，通过远程连接操作

### 架构

```
┌─────────────────────────────────────────────────────────────────┐
│  你的电脑 (运行 Trae/Cursor)                                     │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  mcp_cheatengine_remote.py  (TCP 客户端)                 │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              │ TCP (端口 17171)
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  游戏电脑 (运行 Cheat Engine)                                    │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  ce_tcp_bridge_server.py  (TCP 服务器)                   │   │
│  │  ┌─────────────────────────────────────────────────┐   │   │
│  │  │  Named Pipe: \\.\pipe\CE_MCP_Bridge_v99          │   │   │
│  │  └─────────────────────────────────────────────────┘   │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              │                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  Cheat Engine + ce_mcp_bridge.lua                       │   │
│  └─────────────────────────────────────────────────────────┘   │
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
# 3. 启动 TCP 桥接服务器
python Remote_TCP_Bridge/ce_tcp_bridge_server.py
```

#### 2. 在你的电脑上（运行 Trae）

```bash
# 安装依赖
pip install mcp

# 设置环境变量
set CE_REMOTE_HOST=192.168.1.100  # 游戏电脑IP
set CE_REMOTE_PORT=17171

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
        "CE_REMOTE_PORT": "17171"
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

所有原版功能都可用：

- **内存操作**: 读取内存、整数、字符串、指针链扫描
- **代码分析**: 反汇编、函数分析、结构体解析、RTTI 类名识别
- **调试**: 硬件断点、数据断点、DBVM 隐形追踪
- **43+ 个 MCP 工具**

---

## 安全提示

1. **仅在可信网络中使用**: 默认没有加密，建议在局域网或 VPN 中使用
2. **限制访问**: 在防火墙中限制只允许特定 IP 访问
3. **使用 SSH 隧道**: 如需通过互联网连接，建议使用 SSH 隧道

---

## 许可证

与原项目相同，遵循原项目的许可证。

---

## 致谢

基于 [miscusi-peek/cheatengine-mcp-bridge](https://github.com/miscusi-peek/cheatengine-mcp-bridge) 开发，感谢原作者的优秀工作！
