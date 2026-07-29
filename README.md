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
│   ├── core.py          # Agent 核心：聊天循环 + 工具调用（最多 10 轮）
│   ├── providers/       # LLM Provider（OpenAI 兼容接口）
│   └── tools/           # Agent 工具（read_file / write_file / list_directory）
├── frontend/            # 前端界面（纯 HTML/CSS/JS，无构建步骤）
│   ├── index.html
│   ├── style.css
│   └── app.js
├── assets/              # 资源文件（Logo + 宠物精灵图）
│   └── pet/             # 宠物状态图片（idle / work / cry / sleep）
├── scripts/             # 工具脚本
│   └── gen_pet_assets.py  # 用 AI 生成宠物精灵图
├── BRAND.md             # 品牌指南（配色、字体、语气）
├── CONTRIBUTING.md      # 贡献指南
└── PLAN.md              # 开发计划
```

## 架构说明

```
┌─────────────────────────────────┐
│         PyWebView 窗口           │
│   (HTML + CSS + JS 前端)         │
│         ↕ pywebview.api         │
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

- **前后端通信**：JS 调用 `window.pywebview.api.<method>()`，Python 返回 JSON 字符串
- **异步聊天**：`send_message` 在后台线程执行，通过 `evaluate_js` 推送结果给前端
- **宠物状态**：idle / work / cry / sleep，由主进程维护，宠物进程轮询

## 配置

首次运行需在设置面板配置 API Key。配置保存在 `config.json`（已 gitignored）。

| 字段 | 说明 | 默认值 |
|------|------|--------|
| `api_key` | LLM API 密钥 | — |
| `model` | 模型名称 | `gpt-3.5-turbo` |
| `base_url` | API 地址 | `https://api.openai.com/v1` |
| `temperature` | 生成温度 | `0.7` |
| `max_tokens` | 最大 token 数 | `2048` |

## 贡献指南

欢迎贡献！请先阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 许可证

GNU General Public License v3.0

## 灵感来源

*Molly（摩尼）— 一只可乐色和白色的小泰迪犬，MollyPaw 的灵感缪斯。*
