# MollyPaw 开发计划

## 项目概览

- **项目名称**: MollyPaw
- **版本**: Beta 0.0.0.1
- **技术栈**: Python 3.9+ / PyWebView / HTML+CSS+JS
- **目标**: 轻量级跨平台 AI Agent 桌面客户端
- **灵感来源**: 摩尼（Molly）— 一只棕色白色的小泰迪犬

## 里程碑计划

### 里程碑 1: 基础框架 ✅

- [x] 创建项目目录结构
- [x] 编写 BRAND.md（品牌指南）
- [x] 编写 README.md（项目说明）
- [x] 编写 CONTRIBUTING.md（贡献指南）
- [x] 创建 requirements.txt
- [x] 创建 main.py（PyWebView 入口）
- [x] 创建临时 Logo（爪印 SVG）

### 里程碑 2: 核心 Agent 功能 ✅

- [x] agent/core.py — Agent 核心逻辑
- [x] agent/providers/base.py — LLM Provider 基类
- [x] agent/providers/openai_provider.py — OpenAI Provider 实现
- [x] agent/tools/file_tool.py — 文件工具示例
- [x] 基础聊天功能

### 里程碑 3: 前端界面 ✅

- [x] frontend/index.html — 聊天界面
- [x] frontend/style.css — 棕白配色样式
- [x] frontend/app.js — JS 与 Python 通信
- [x] 消息气泡组件
- [x] 输入框和发送按钮

### 里程碑 4: 完善与发布

- [x] 设置面板（API Key 配置）
- [x] 错误处理和加载状态
- [x] 系统托盘支持（pystray）
- [x] 打包为可执行文件（Windows，PyInstaller）
- [ ] GitHub 发布 Beta 0.0.0.1

## 目录结构

`
D:\MollyPaw Agent\
├── main.py                 # PyWebView 入口 + 系统托盘
├── build.bat               # Windows 打包脚本
├── requirements.txt        # Python 依赖
├── agent/                  # Agent 核心
│   ├── __init__.py
│   ├── core.py             # Agent 核心逻辑
│   ├── providers/          # LLM Provider
│   │   ├── __init__.py
│   │   ├── base.py
│   │   └── openai_provider.py
│   └── tools/              # Agent 工具
│       ├── __init__.py
│       └── file_tool.py
├── frontend/               # 前端界面
│   ├── index.html
│   ├── style.css
│   └── app.js
├── assets/                 # 资源文件
│   └── logo-placeholder.svg
├── BRAND.md                # 品牌指南
├── README.md               # 项目说明
├── CONTRIBUTING.md         # 贡献指南
└── PLAN.md                 # 本文件（开发计划）
`

## 技术细节

### PyWebView 窗口

`python
import webview

window = webview.create_window(
    'MollyPaw',
    'frontend/index.html',
    width=1000,
    height=700,
    min_size=(800, 600)
)
webview.start()
`

### JS <-> Python 通信

- Python 端：通过 window.expose() 暴露 API
- JS 端：通过 window.pywebview.api.xxx() 调用

### 系统托盘

- 关闭窗口时自动最小化到系统托盘
- 托盘图标右键菜单：Show MollyPaw / Quit
- 使用 pystray + Pillow 实现
- 无 pystray 时自动降级为普通关闭模式

### LLM Provider 设计

- BaseProvider 定义接口（init, chat, stream）
- OpenAIProvider 实现 OpenAI API 对接
- 未来可扩展：ClaudeProvider, LocalProvider 等

### 打包

- Windows: 运行 build.bat（PyInstaller --onefile --windowed）
- macOS/Linux: 待后续版本支持

## 配色参考

- 深棕 #6B4226 — 主文字
- 中棕 #8B5E3C — 导航栏
- 浅棕 #A67B5B — 悬停状态
- 奶棕 #D2B48C — 背景渐变
- 纯白 #FFFFFF — 主背景
- 米白 #FFF8F0 — 次级背景
- 爪印橙 #D4823A — CTA 按钮

## 待办事项

- [ ] 等妈妈画摩尼头像 Logo
- [ ] 创建 GitHub 仓库 LK-BLOG/MollyPaw
- [ ] 测试跨平台兼容性

## 时间线

- **本周**: 完成里程碑 1（基础框架）✅
- **下周**: 完成里程碑 2（核心 Agent）✅
- **第三周**: 完成里程碑 3（前端界面）✅
- **第四周**: 完成里程碑 4（发布 Beta）— 进行中

---

*最后更新: 2026-07-26*