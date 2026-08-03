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

当前版本为 **v0.1.5 — Progress-Aware Runtime**。

现阶段已经完成：

- `vortex` CLI 入口与 Textual 全屏 TUI
- DeepSeek `deepseek-v4-flash` 默认模型接入
- OpenAI-compatible Chat Completions 协议
- 基于 `AsyncOpenAI` 的异步流式通信
- DeepSeek 原生流式 Tool Calling 与跨分片参数组装
- 默认关闭思考模式
- 当前进程内的临时多轮对话
- 自研进展感知单 Agent Loop 与显式 Run/Step 状态
- Tool Registry、统一执行管道和 Observation 回填
- `workspace_overview`、`list_directory`、`read_file`、`search_files` 四个只读工作区工具
- `apply_patch` 精确修改单个现有 UTF-8 文件，修改前展示完整 Diff
- `run_command` 执行项目已有的测试、类型检查、Lint、构建和版本控制检查
- 面向大型仓库的有界结构概览和大文件 UTF-8 连续分块读取
- 绝对路径、路径穿越和符号链接逃逸防护
- 交互模式默认不设置 Run 级总 Step 或总工具次数上限，新 Observation 会持续续期长任务
- 每轮工具批量上限、重复 Observation 检测、连续控制错误熔断与安全总结
- `Allow once`、`Allow for session`、`Deny` 会话级工具审批
- 每个工作区会话按工具名称保存内存审批缓存，退出后自动清除
- 写操作仅按当前任务授权，任务结束后展示文件与增删行汇总
- 支持 Review 完整 Diff，并将最新一轮全部修改安全 Revert 到首次编辑前
- 原子文件替换、预览后陈旧检测，以及外部修改冲突保护
- 命令逐次审批、工作目录限制、禁用隐式 Shell、动态超时和进程组取消
- stdout/stderr 有界采集、退出码回填，以及验证失败后的 Agent 自主修复与重试
- `run_command` 参数校验与进程执行阶段区分，以及 JSON 编码 argv 的保守安全归一化
- 命令非零退出作为诊断 Observation 推动迭代，不再被等同于 Runtime 无进展错误
- TUI 工具参数、结果预览、状态和耗时展示
- 工具轮临时行动文本自动收起，安全总结阶段拒绝展示供应商内部 Tool Calling 协议
- 对话文本选择、系统剪贴板复制、内部粘贴与 macOS `pbcopy` 兼容
- 有选区时 `Ctrl+C` 复制，无选区且正在生成时取消，`Ctrl+Q` 退出
- 认证、余额、限流、超时和服务异常的安全错误提示
- GitHub-flavored Markdown 增量渲染
- 标题、强调、列表、代码高亮和表格展示
- Token 用量读取与状态栏展示
- Fake Provider、Fake Tool、MockTransport 与无头 TUI 确定性测试
- Ruff、mypy strict 和 pytest 质量门禁

> 当前 Agent 可以读取、搜索、修改现有文本文件并执行经过逐次审批的非交互命令，但不能创建、
> 删除或重命名文件。命令不经过隐式 Shell；其副作用暂不纳入 Patch Revert，也尚未运行在 Sandbox 中。

## 预期目标

Vortex 将按可验证的纵向切片逐步演进：

1. **Chat Foundation（已完成）**：真实模型、流式输出、临时多轮对话与错误处理
2. **Single-Agent Runtime（已完成）**：有界 Agent Loop、Tool Calling 与只读工作区工具
3. **Reviewable Editing（已完成）**：按轮授权的精确 Patch、Diff Review 与整轮 Revert
4. **Verified Execution（已完成）**：受控命令执行、外部验证与失败修复闭环
5. **Progress-Aware Runtime（已完成）**：长任务续期、停滞检测与可靠工具错误反馈
6. **Safety & Trace**：执行 Sandbox、完整 Trace 与运行审计
7. **Session & Context**：会话持久化、上下文构建、Token 预算与压缩
8. **MCP & Multi-Agent**：工具发现、MCP 接入和边界清晰的子 Agent 协作
9. **Web Console**：会话、任务、运行过程、事件与产物的管理界面

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
    ├── schedule → Progress-aware Budget Scheduler
    ├── model → ModelProvider → DeepSeek Chat Completions
    └── tool → Session Approval → Tool Registry → Tool Executor
                                                   ├── workspace_overview
                                                   ├── list_directory
                                                   ├── read_file (chunked)
                                                   ├── search_files
                                                   ├── apply_patch
                                                   │      └── TurnChangeTracker
                                                   └── run_command
```

当前实现遵循以下边界：

- TUI 不直接依赖 DeepSeek 或 OpenAI SDK 对象
- Runtime 只消费 Vortex 自己定义的 `Message`、`ModelEvent`、`ToolCall` 和 `ToolResult`
- Provider 负责协议转换、流式 Tool Call 拼接和模型错误归一化
- Tool Executor 负责工具查找、参数校验、超时和安全错误转换
- 权限管理器让只读工具按次/会话授权，让写工具只在当前任务内授权
- 命令执行始终逐次授权，不能进入按轮或按会话缓存
- 写工具先 Prepare 出精确 Diff，再审批和原子提交，避免“批准未知修改”
- 最新任务的首次文件快照只保存在内存；下一任务开始即默认接受并丢弃快照
- `run_command` 使用 argv 启动子进程，不解释管道、重定向、`&&` 等 Shell 语法
- Agent 根据真实项目清单选择验证工具，不在 Runtime 中硬编码 Python、Node.js 等语言策略
- 交互 Run 不消耗固定总工具额度；不同调用得到的新 Observation 会重置停滞计数
- 单轮超额调用只延后处理；重复 Observation 或连续控制层错误才触发安全总结
- 命令参数校验会明确标记 `Executed: false`，真实进程结果会标记 `Executed: true`
- `run_command` 只对可确定解析为非空 `list[str]` 的 JSON 数组字符串执行安全归一化
- 命令非零退出、目标未找到等新诊断结果属于有效进展；相同结果重复出现才计入停滞
- 工具轮中的临时模型文本不进入最终对话，安全总结中的内部工具协议不会被渲染
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
MAX_TOOLS_PER_ITERATION=8
MAX_STALLED_ITERATIONS=3
MAX_CONSECUTIVE_TOOL_ERRORS=6
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
│   ├── tools/                  # Registry、Executor、工作区工具与轮次变更跟踪
│   └── permissions/            # 按次、按轮、按会话审批与内存允许缓存
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
长任务续期、停滞收尾、大文件分块、Patch 原子性、冲突 Revert、命令参数归一化、子进程
超时/取消/输出截断、验证失败迭代、临时工具文本收起、Markdown、复制、错误和历史提交。

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
- 尚未实现上下文压缩；长任务不会被固定工具额度截断，但模型输入与调用成本仍会持续增长
- 暂不支持 `/model` 等斜杠命令
- `apply_patch` 只修改一个现有 UTF-8 文件，不支持创建、删除或重命名
- 只支持最新一轮整体 Revert；开始下一轮或退出进程后不再可撤销
- `run_command` 不提供隐式 Shell、交互程序或后台任务能力
- 命令会执行本地项目代码，当前没有容器/Sandbox 或网络隔离，其产生的文件变化不支持 Revert
- 当前审批缓存和修改快照均不持久化
- 暂不支持 MCP 和多 Agent
- 暂不包含数据库、后台 Core 服务和 Web 管理端
- 当前仅提供 DeepSeek Provider

这些限制是当前里程碑的主动边界，不代表最终能力范围。

## 许可证

本项目基于 [MIT License](LICENSE) 开源。你可以在保留版权与许可证声明的前提下使用、修改、
分发和商用本项目。
