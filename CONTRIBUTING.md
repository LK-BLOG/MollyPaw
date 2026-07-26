# 贡献指南

感谢你有兴趣为 MollyPaw 做出贡献！这份指南会帮你快速上手。

## 如何参与

1. **Fork** 这个仓库
2. **Clone** 你 Fork 的仓库到本地
3. 创建一个新分支：`git checkout -b your-feature-name`
4. 做你的修改
5. 提交：`git commit -m "简短描述你的改动"`
6. Push 到你的 Fork：`git push origin your-feature-name`
7. 打开一个 **Pull Request**

## 开发环境

### 环境要求
- Python >= 3.9
- pip

### 安装步骤

```bash
# 克隆你 Fork 的仓库
git clone https://github.com/YOUR-USERNAME/MollyPaw.git
cd MollyPaw

# 安装依赖
pip install -r requirements.txt

# 运行项目
python main.py
```

## 项目结构

```
MollyPaw/
├── main.py              # PyWebView 入口
├── requirements.txt     # Python 依赖
├── agent/               # Agent 核心逻辑
│   ├── core.py          # Agent 核心
│   ├── providers/       # LLM Provider（可扩展）
│   └── tools/           # Agent 工具（可扩展）
├── frontend/            # 前端界面
│   ├── index.html
│   ├── style.css
│   └── app.js
├── assets/              # 资源文件（Logo 等）
├── BRAND.md             # 品牌指南
├── README.md
└── CONTRIBUTING.md      # 就是这个文件
```

## 代码规范

- Python 代码遵循 PEP 8 风格
- 前端代码保持简洁，不用框架
- 新功能请尽量写注释，方便其他人理解
- 提交信息用中文或英文都可以，但要简短清楚

## 添加新的 LLM Provider

MollyPaw 支持扩展 LLM Provider。如果你想添加新的 Provider：

1. 在 `agent/providers/` 目录下创建新文件
2. 继承 `BaseProvider`（在 `agent/providers/base.py`）
3. 实现必要方法
4. 在设置中注册你的 Provider

## 添加新的 Agent 工具

1. 在 `agent/tools/` 目录下创建新文件
2. 定义工具的名称、描述、参数
3. 在 Agent 核心中注册工具

## 提交 Issue

发现了 Bug？有新功能想法？欢迎在 GitHub 上提交 Issue！

请在 Issue 中说明：
- 你遇到了什么问题（Bug）或想要什么功能（Feature）
- 你的操作系统和 Python 版本
- 复现步骤（如果是 Bug）

## 行为准则

- 尊重每一位贡献者
- 保持友善和建设性的讨论
- 接受建设性的批评
- 关注对社区最有利的事情

## 许可证

贡献代码即表示你同意你的代码在 GPLv3 许可证下发布。

## 联系方式

- GitHub: [LK-BLOG](https://github.com/LK-BLOG)
- 邮箱: 542548450@qq.com

感谢你的贡献！就像摩尼一样，每一次陪伴都很重要。🐾