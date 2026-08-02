<div align="center">

# Vortex

**A local, observable, and controllable Agent Runtime**

面向本地工作区的现代 Agent Runtime 学习与工程实践项目

[![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Textual](https://img.shields.io/badge/Textual-TUI-8B5CF6?style=flat-square)](https://textual.textualize.io/)
[![DeepSeek](https://img.shields.io/badge/DeepSeek-V4%20Flash-4D6BFE?style=flat-square&logo=deepseek&logoColor=white)](https://api-docs.deepseek.com/)
[![uv](https://img.shields.io/badge/uv-package%20manager-DE5FE9?style=flat-square&logo=uv&logoColor=white)](https://docs.astral.sh/uv/)
[![Ruff](https://img.shields.io/badge/Ruff-lint-D7FF64?style=flat-square&logo=ruff&logoColor=black)](https://docs.astral.sh/ruff/)
[![mypy](https://img.shields.io/badge/mypy-strict-2A6DB2?style=flat-square)](https://mypy-lang.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](LICENSE)

</div>

## 项目定位

Vortex 是一个面向本地工作区的 Agent Runtime。项目参考 Claude Code、Codex CLI 与优秀开源
Agent 项目的交互方式和工程经验，但不以复刻某个产品为目标，也不面向客服、教育、办公等特定
垂直业务。

项目希望从运行时视角理解和实现现代 Agent 的关键机制：模型如何持续感知任务状态、选择行动、
调用受控工具、接收观察结果并迭代执行；系统又如何管理上下文、权限、会话、事件和失败恢复。

Vortex 的核心价值不是“给大模型套一个聊天界面”，而是逐步构建一套：

- 可理解：核心循环、状态与模块边界由项目自主设计
- 可控制：工具调用、文件操作和 Shell 执行具有明确权限边界
- 可观察：模型、工具和任务运行过程能够被记录、追踪和回放
- 可扩展：CLI/TUI、Web、MCP 与多 Agent 共享统一运行时语义
- 可测试：核心行为可通过 Fake Provider 和确定性事件验证，不依赖真实模型输出

更完整的设计背景见 [docs/description.md](docs/description.md)。

## 当前进度

当前版本为 **v0.0.2 — Streaming Chat Foundation**。

现阶段已经完成：

- `vortex` CLI 入口与 Textual 全屏 TUI
- DeepSeek `deepseek-v4-flash` 默认模型接入
- OpenAI-compatible Chat Completions 协议
- 基于 `AsyncOpenAI` 的异步流式通信
- 默认关闭思考模式
- 当前进程内的临时多轮对话
- `Ctrl+C` 取消生成与 `Ctrl+Q` 退出
- 认证、余额、限流、超时和服务异常的安全错误提示
- GitHub-flavored Markdown 增量渲染
- 标题、强调、列表、代码高亮和表格展示
- Token 用量读取与状态栏展示
- Ruff、mypy strict 和 pytest 质量门禁

> 当前还没有实现工具调用和 Agent Loop。v0.0.2 的目标是先建立稳定、可取消、可测试的模型通信
> 底座，再在此基础上增加 Agent 行动能力。

## 预期目标

Vortex 将按可验证的纵向切片逐步演进：

1. **Chat Foundation**：真实模型、流式输出、临时多轮对话与错误处理
2. **Model & Command UX**：模型配置、`/model` 等斜杠命令和基础运行参数
3. **Agent Runtime**：显式 Agent Loop、终止条件、Tool Calling 与 Observation 回填
4. **Safety & Trace**：工具权限、人工审批、类型化事件、耗时与 Token 追踪
5. **Session & Context**：会话持久化、上下文构建、Token 预算与压缩
6. **MCP & Multi-Agent**：工具发现、MCP 接入和边界清晰的子 Agent 协作
7. **Web Console**：会话、任务、运行过程、事件与产物的管理界面

长期目标是让 Vortex 能够在本地工作区中完成一条可追溯的 Agent 执行链路：

```text
Task
  → Context
  → Model
  → Tool Call
  → Permission / Approval
  → Tool Result
  → Observation
  → Next Step
  → Completed / Failed / Cancelled
```

## 当前架构

```text
Textual TUI
    │
    ▼
ChatService ─────────────── In-memory message history
    │
    ▼
ModelProvider protocol
    │
    ▼
DeepSeekProvider
    │
    ▼
DeepSeek Chat Completions API
```

当前实现遵循以下边界：

- TUI 不直接依赖 DeepSeek 或 OpenAI SDK 对象
- Runtime 只消费 Vortex 自己定义的 `Message` 和 `ModelEvent`
- Provider 负责协议转换、流解析和错误归一化
- 一轮对话成功完成后，用户消息与模型回复才会原子写入临时历史
- 取消或失败的回复可以保留在界面，但不会污染下一轮模型上下文

## 技术栈

| 领域 | 技术 | 当前用途 |
|---|---|---|
| 语言 | Python 3.12+ | Runtime、CLI、TUI 与测试 |
| 包管理 | uv | Python、依赖、锁文件、运行与构建 |
| CLI | Typer | `vortex` 命令入口 |
| TUI | Textual + Rich | 终端布局、交互和样式 |
| 模型通信 | OpenAI Python SDK | 访问 DeepSeek OpenAI-compatible API |
| 默认模型 | DeepSeek V4 Flash | 当前默认对话模型 |
| 配置 | pydantic-settings | `.env` 加载、默认值和密钥类型 |
| 异步基础 | asyncio | 流式响应、取消与 UI 非阻塞执行 |
| 测试 | pytest + pytest-asyncio | 单元测试与无头 TUI 测试 |
| 质量 | Ruff + mypy | 格式、Lint 与严格静态类型检查 |

Vortex 的 Agent Loop、事件模型、上下文构建和工具管道将自主设计。核心 Runtime 不计划建立在
LangGraph 等通用编排框架之上；相关框架可用于后续对比实验，但不会隐藏项目最希望展示的运行机制。

## 安装与使用

### 环境要求

- Python 3.12 或更高版本
- [uv](https://docs.astral.sh/uv/)
- 可用的 DeepSeek API Key

macOS 可以通过 Homebrew 安装 uv：

```bash
brew install uv
```

也可以使用 uv 官方安装脚本：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 1. 安装依赖

在 Vortex 项目根目录执行：

```bash
uv sync
```

### 2. 配置 DeepSeek API Key

复制环境变量模板：

```bash
cp .env.example .env
```

编辑 `.env`：

```dotenv
DEEPSEEK_API_KEY=your-new-api-key
VORTEX_MODEL=deepseek-v4-flash
DEEPSEEK_BASE_URL=https://api.deepseek.com
```

`.env` 已被 Git 忽略，`.env.example` 只保存配置名称，不保存任何真实密钥。请勿在代码、测试、
Issue、提交记录或终端截图中暴露 API Key。

### 3. 启动 Vortex

```bash
uv run vortex
```

进入界面后：

| 操作 | 快捷键 |
|---|---|
| 提交消息 | `Enter` |
| 取消当前回复 | `Ctrl+C` |
| 退出 Vortex | `Ctrl+Q` |

### 安装为本地命令

开发期间可以使用 editable 模式安装：

```bash
uv tool install --editable .
vortex
```

如果之前安装过旧版本，可以重新安装：

```bash
uv tool install --editable . --force
```

## 项目结构

```text
vortex/
├── pyproject.toml              # 包元数据、依赖和质量工具配置
├── uv.lock                     # 可复现依赖锁文件
├── README.md                   # 项目首页
├── AGENTS.md                   # Agent 开发约束
├── docs/
│   └── description.md          # 项目定位与长期设计说明
├── src/vortex/
│   ├── cli/                    # Typer 命令入口
│   ├── tui/                    # Textual 应用、页面、组件与样式
│   ├── config/                 # 类型化配置加载
│   ├── domain/                 # 供应商无关的领域对象和事件
│   ├── providers/              # 模型供应商协议与适配器
│   ├── runtime/                # 当前对话运行时，后续承载 Agent Loop
│   ├── tools/                  # 预留：工具定义与注册
│   ├── permissions/            # 预留：策略、审批与权限
│   ├── persistence/            # 预留：会话和运行状态持久化
│   ├── protocol/               # 预留：客户端与 Runtime 事件协议
│   └── api/                    # 预留：Core API
└── tests/
    ├── unit/                   # 配置、Runtime 与 Provider 测试
    ├── tui/                    # Textual 无头交互测试
    └── support/                # Fake Provider 等测试辅助对象
```

## 开发与质量检查

运行全部质量门禁：

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
uv lock --check
```

构建发行包：

```bash
uv build --no-sources
```

自动测试不会访问真实模型 API。DeepSeek 协议通过本地 MockTransport 验证，Runtime 与 TUI 使用
确定性的 Fake Provider 验证流式分片、Markdown、取消、错误和多轮历史。

## 项目原则

- 先打通可靠的纵向链路，再增加功能数量
- 保持领域模型和供应商 SDK 解耦
- 将取消、超时和失败视为正常运行状态
- 用类型化事件表达执行事实，不从日志文本反推状态
- 权限审批与执行隔离分层设计
- 所有关键 Runtime 行为都应能够离线、确定性测试
- 不将模型输出、工具参数或外部内容默认视为可信输入

## 当前限制

- 对话历史只保存在当前进程内，退出后不会恢复
- 暂不支持 `/model` 等斜杠命令
- 暂不支持 Tool Calling、MCP、Agent Loop 和多 Agent
- 暂不包含数据库、后台 Core 服务和 Web 管理端
- 当前仅提供 DeepSeek Provider

这些限制是当前里程碑的主动边界，不代表最终能力范围。

## 许可证

本项目基于 [MIT License](LICENSE) 开源。你可以在保留版权与许可证声明的前提下使用、修改、
分发和商用本项目。
