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

当前版本为 **v0.2.0 — Safe Workspace Exploration**。

现阶段已经完成：

- `vortex` CLI 入口与 Textual 全屏 TUI
- DeepSeek `deepseek-v4-flash` 默认模型接入
- OpenAI-compatible Chat Completions 协议
- 基于 `AsyncOpenAI` 的异步流式通信
- DeepSeek 原生流式 Tool Calling 与跨分片参数组装
- 默认关闭思考模式
- 当前进程内的临时多轮对话
- 自研有界单 Agent Loop 与显式 Run/Step 状态
- Tool Registry、统一执行管道和 Observation 回填
- `workspace_overview`、`list_directory`、`read_file`、`search_files` 四个只读工作区工具
- 面向大型仓库的有界结构概览和大文件 UTF-8 连续分块读取
- 绝对路径、路径穿越和符号链接逃逸防护
- 24 个探索 Step、64 次工具调用和预算耗尽后的无工具强制总结
- `Allow once`、`Allow for session`、`Deny` 会话级工具审批
- 每个工作区会话按工具名称保存内存审批缓存，退出后自动清除
- TUI 工具参数、结果预览、状态和耗时展示
- 对话文本选择、系统剪贴板复制、内部粘贴与 macOS `pbcopy` 兼容
- 有选区时 `Ctrl+C` 复制，无选区且正在生成时取消，`Ctrl+Q` 退出
- 认证、余额、限流、超时和服务异常的安全错误提示
- GitHub-flavored Markdown 增量渲染
- 标题、强调、列表、代码高亮和表格展示
- Token 用量读取与状态栏展示
- Fake Provider、Fake Tool、MockTransport 与无头 TUI 确定性测试
- Ruff、mypy strict 和 pytest 质量门禁

> 当前 Agent 只具备经过会话审批、且受工作区约束的读取与搜索能力，不会修改文件或执行 Shell。
> 持久化审批策略、上下文压缩、MCP 和多 Agent 仍属于后续里程碑。

## 预期目标

Vortex 将按可验证的纵向切片逐步演进：

1. **Chat Foundation（已完成）**：真实模型、流式输出、临时多轮对话与错误处理
2. **Single-Agent Runtime（已完成）**：有界 Agent Loop、Tool Calling 与只读工作区工具
3. **Model & Command UX**：模型配置、`/model` 等斜杠命令和基础运行参数
4. **Safety & Trace**：扩展写操作权限、执行隔离、完整 Trace 与运行审计（只读审批已完成）
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
AgentRuntime ─────────────── In-memory committed history
    │
    ├── model → ModelProvider → DeepSeek Chat Completions
    └── tool → Session Approval → Tool Registry → Tool Executor
                                                   ├── workspace_overview
                                                   ├── list_directory
                                                   ├── read_file (chunked)
                                                   └── search_files
```

当前实现遵循以下边界：

- TUI 不直接依赖 DeepSeek 或 OpenAI SDK 对象
- Runtime 只消费 Vortex 自己定义的 `Message`、`ModelEvent`、`ToolCall` 和 `ToolResult`
- Provider 负责协议转换、流式 Tool Call 拼接和模型错误归一化
- Tool Executor 负责工具查找、参数校验、超时和安全错误转换
- 权限管理器在执行前请求明确决定，并只在当前工作区进程会话缓存工具级允许项
- 达到探索预算后关闭工具能力，要求模型基于已有 Observation 生成最佳最终答案
- 一次 Run 成功完成后，用户消息、工具调用、Observation 和最终回复才会原子提交
- 取消、失败或达到上限的内容可以保留在界面，但不会污染下一轮模型上下文

## 技术栈

| 领域 | 技术 | 当前用途 |
|---|---|---|
| 语言 | Python 3.12+ | Runtime、CLI、TUI 与测试 |
| 包管理 | uv | Python、依赖、锁文件、运行与构建 |
| CLI | Typer | `vortex` 命令入口 |
| TUI | Textual + Rich | 终端布局、交互和样式 |
| 模型通信 | OpenAI Python SDK | 访问 DeepSeek OpenAI-compatible API |
| 默认模型 | DeepSeek V4 Flash | 当前默认 Agent 决策模型 |
| 配置 | pydantic-settings | 项目私有 `.env`、默认值和密钥类型 |
| 异步基础 | asyncio | 流式响应、取消与 UI 非阻塞执行 |
| 测试 | pytest + pytest-asyncio | 单元测试与无头 TUI 测试 |
| 质量 | Ruff + mypy | 格式、Lint 与严格静态类型检查 |

Vortex 的 Agent Loop、运行事件和工具管道由项目自主实现。核心 Runtime 不建立在
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

### 2. 配置 Vortex 私有模型凭证

复制环境变量模板：

```bash
cp .env.example .env
```

编辑 `.env`：

```dotenv
DEEPSEEK_API_KEY=your-new-api-key
VORTEX_MODEL=deepseek-v4-flash
DEEPSEEK_BASE_URL=https://api.deepseek.com
MAX_AGENT_ITERATIONS=24
MAX_AGENT_TOOL_CALLS=64
TOOL_TIMEOUT_SECONDS=15
```

这份 `.env` 固定属于 Vortex 应用。无论从哪个工作区启动，Vortex 都读取仓库根目录的这份私有
配置，不读取当前工作区的 `.env`，也不接受 Shell 中的同名变量覆盖。当前阶段的默认模型能力由
Vortex 项目统一提供，不支持用户自带 API Key。

`.env` 已被 Git 忽略，`.env.example` 只保存配置名称，不保存任何真实密钥。请勿在代码、测试、
Issue、提交记录、构建产物或终端截图中暴露 API Key。

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
```

安装后可以进入任意工作区直接启动，启动目录会成为 Agent 的工作区，而模型凭证仍来自 Vortex
仓库根目录：

```bash
cd /path/to/workspace
vortex
```

如果之前安装过旧版本，可以重新安装：

```bash
uv tool install --editable . --force --reinstall
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
│   ├── runtime/                # 单 Agent Loop 与内存运行状态
│   ├── tools/                  # Registry、Executor 与只读工作区工具
│   └── permissions/            # 会话级审批协议、交互回调与内存允许缓存
└── tests/
    ├── unit/                   # 配置、Runtime 与 Provider 测试
    ├── tui/                    # Textual 无头交互测试
    └── support/                # Fake Provider 等测试辅助对象
```

持久化、共享协议、Core API 与 Web 模块将在对应能力开始实现时创建，不保留空目录占位。

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
确定性的 Fake Provider、Fake Tool 和 Fake Approval 验证流式分片、工具循环、审批、Observation、
预算收尾、大文件分块、Markdown、复制、取消、错误和原子历史提交。

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
- 当前只有读取、目录浏览和文本搜索工具，不支持文件修改与 Shell
- 当前审批缓存不持久化，也尚未包含写操作和 Shell 的高风险策略
- 暂不支持 MCP 和多 Agent
- 暂不包含数据库、后台 Core 服务和 Web 管理端
- 当前仅提供 DeepSeek Provider

这些限制是当前里程碑的主动边界，不代表最终能力范围。

## 许可证

本项目基于 [MIT License](LICENSE) 开源。你可以在保留版权与许可证声明的前提下使用、修改、
分发和商用本项目。
