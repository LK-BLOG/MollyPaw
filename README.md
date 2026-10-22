# MollyPaw

> **Your AI, right at your paw.**

一只小泰迪犬启发的全平台 AI Agent 桌面客户端。

## 什么是 MollyPaw？

MollyPaw 是一款基于 **Python + PyWebView** 构建的轻量级 AI Agent 桌面应用。
它让你在本地运行 AI 助手，对接任意 LLM API，拥有一个真正属于你自己的 Agent。

灵感来自一只叫摩尼（Molly）的小泰迪犬——温柔、聪明、随时陪伴。

## 主要特性

- **超轻量** — 不需要 Rust，不需要 Node.js，只需要 Python
- **跨平台** — Windows / macOS / Linux，一套代码全平台运行
- **PyWebView 驱动** — 使用系统自带 Web 引擎，启动快、体积小
- **Python Agent 后端** — 灵活的 Agent 框架，可对接 OpenAI / Claude / 本地模型
- **温暖的界面** — 棕色+白色设计，来自摩尼的毛色
- **桌面宠物** — 可爱的小泰迪陪你工作，状态实时同步
- **开源免费** — GPLv3 许可证，欢迎贡献

## 快速开始

### 环境要求

- [Python](https://python.org/) >= 3.9

### 安装

```bash
# 克隆仓库
git clone https://github.com/LK-BLOG/MollyPaw.git
cd MollyPaw

# 安装依赖
pip install -r requirements.txt

# 运行
python main.py

# 调试模式（开启 webview devtools）
python main.py --debug
```

### 打包为可执行文件（Windows）

```bash
.\build.bat
```

打包完成后，exe 文件位于 `dist\MollyPaw.exe`。

## 项目结构

```
MollyPaw/
├── main.py              # 入口：PyWebView 窗口 + 系统托盘 + 宠物 HTTP 服务
├── pet.py               # 桌面宠物（独立 tkinter 进程，轮询状态）
├── build.bat            # Windows 打包脚本
├── requirements.txt     # Python 依赖
├── config.json          # 运行时配置（gitignored，需手动创建或通过设置面板配置）
├── agent/               # Agent 核心逻辑
│   ├── core.py          # Agent 核心：聊天循环 + 工具调用 + 流式 + 取消
│   ├── service.py       # 业务门面（本地 UI 与远程设备共用）
│   ├── cancel.py        # 取消令牌（停止按钮的底座）
│   ├── relay/           # 远程互联（加密 / 中继客户端 / 设备管理 / 二维码）
│   ├── providers/       # LLM Provider（OpenAI 兼容接口）
│   └── tools/           # Agent 工具（文件 / 命令 / 记忆 / 技能 / 网页）
├── frontend/            # 前端界面（纯 HTML/CSS/JS，无构建步骤）
│   ├── index.html
│   ├── style.css
│   └── app.js
├── assets/              # 资源文件（Logo + 宠物精灵图）
│   └── pet/             # 宠物状态图片（idle / work / cry / sleep）
├── tools/               # 工具脚本（CLI 模拟手机、截图验收、诊断）
├── tests/               # pytest 测试
├── BRAND.md             # 品牌指南（配色、字体、语气）
├── CONTRIBUTING.md      # 贡献指南
├── CHANGELOG.md         # 变更记录
└── pytest.ini
```

## 远程互联（手机 ↔ 电脑）

手机通过 Cloudflare 中继连上这台电脑，全程端到端加密。

```
Android App ──wss──┐
                   ├──> wss://mollypaw-online.pages.dev/server
PC (MollyPaw) ─wss─┘         │
                             └──> Durable Object（盲转发，只路由不解析）
```

**关键点**

- **中继看不到内容**：所有业务帧都是 AES-256-GCM 密文，AAD 绑定房间/角色/序号。
- **一键配对**：设置里点「添加设备」出二维码，扫一下就连上 —— 手机不用手输密钥。
  配对码 15 分钟有效、一次性。
- **不装新依赖**：二维码是自写的编码器（`agent/relay/qr.py`），
  与标准实现逐模块比对验证过。

**在电脑上开启**：设置 → 远程互联 → 选「官方中继」→ 开启 → 添加设备。

**相关仓库**

- `MollyPaw-Relay` — 中继（Cloudflare Worker + Pages Function + 本地开发用 Python 中继）
- `MollyPaw-Android` — 安卓客户端（Kotlin + Compose）

**不想用手机？** 有个命令行版模拟手机（`tools/mp_phone.py`），
不需要真机就能验证整条链路。

## 架构说明

```
┌─────────────────────────────────┐
│         PyWebView 窗口           │
│   (HTML + CSS + JS 前端)         │
│         ↕ HTTP API             │
│         Python 后端              │
│   AgentCore → Provider → LLM    │
│   ToolRegistry → FileTool       │
├─────────────────────────────────┤
│   HTTP 服务 (127.0.0.1:18765)   │
│   提供宠物图片 + /state 接口      │
├─────────────────────────────────┤
│   宠物进程 (tkinter)             │
│   每秒轮询 /state 切换动画        │
└─────────────────────────────────┘
```

- **前后端通信**：前端只通过 `http://127.0.0.1:18765/api/*` HTTP 接口通信
- **异步事件**：前端轮询 `/api/events` 获取聊天、工具和审批事件
- **宠物状态**：idle / work / cry / sleep，由主进程维护，宠物进程轮询

## 配置

首次运行需在设置面板配置 API Key。配置保存在 `config.json`（已 gitignored）。

| 字段 | 说明 | 默认值 |
|------|------|--------|
| `provider_id` | 供应商 ID | `openai` |
| `api_key` | 当前供应商 API 密钥 | — |
| `model` | 原始模型 ID | —（从供应商实时拉取） |
| `base_url` | 自定义供应商 API 地址 | 内置供应商自动配置 |
| `protocol` | `chat` 或 `responses` | 内置供应商自动配置 |
| `temperature` | 生成温度（Kimi 等供应商可能不支持） | `0.7` |
| `max_tokens` | 最大 token 数 | `2048` |

## 贡献指南

欢迎贡献！请先阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 许可证

GNU General Public License v3.0

## 灵感来源

*Molly（摩尼）— 一只可乐色和白色的小泰迪犬，MollyPaw 的灵感缪斯。*
