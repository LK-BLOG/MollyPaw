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
- **开源免费** — GPLv3 许可证，欢迎贡献

## 技术架构

```
+-----------------------------+
|       MollyPaw 桌面端        |
|                             |
|  PyWebView 窗口              |
|  (HTML + CSS + JS)          |
|    - 聊天界面                |
|    - Agent 管理              |
|    - 设置面板                |
|           |                 |
|           v  pywebview.api  |
|                             |
|  Python 后端                 |
|    - Agent 核心逻辑          |
|    - LLM Provider 对接       |
|    - 工具调用                |
|    - 插件系统                |
+-----------------------------+
```

## 快速开始

### 环境要求

- [Python](https://python.org/) >= 3.9
- 仅此而已！不需要 Rust，不需要 Node.js

### 安装

```bash
# 克隆仓库
git clone https://github.com/LK-BLOG/MollyPaw.git
cd MollyPaw

# 安装依赖
pip install -r requirements.txt

# 运行
python main.py
```

## 项目结构

```
MollyPaw/
├── main.py              # PyWebView 入口
├── requirements.txt     # Python 依赖
├── agent/               # Agent 核心逻辑
│   ├── __init__.py
│   ├── core.py          # Agent 核心
│   ├── providers/       # LLM Provider
│   │   ├── __init__.py
│   │   ├── base.py
│   │   └── openai_provider.py
│   └── tools/           # Agent 工具
│       ├── __init__.py
│       └── file_tool.py
├── frontend/            # 前端界面
│   ├── index.html
│   ├── style.css
│   └── app.js
├── assets/              # 资源文件
│   ├── logo-placeholder.svg
│   └── icon.ico
├── BRAND.md             # 品牌指南
└── README.md
```

## 贡献指南

欢迎贡献！请先阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 许可证

GNU General Public License v3.0

## 灵感来源

*Molly（摩尼）— 一只可乐色和白色的小泰迪犬，MollyPaw 的灵感缪斯。*