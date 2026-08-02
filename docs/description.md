# Vortex 项目说明

## 1. 项目定位

Vortex 是一个面向本地工作区的 Agent Runtime。它以 Claude Code、Codex CLI、KamaClaude 等本地开发 Agent 的运行方式为参考，目标是系统实现和展示现代 Agent 的核心运行机制，而不是复刻某个已有产品的功能与界面。

Vortex 不面向客服、教育、办公等特定业务场景，也不以知识库问答或聊天页面作为主要成果。项目关注的是：当大模型能够读取文件、调用工具、执行命令并持续完成任务时，如何构建一套可理解、可控制、可持久化、可观察的运行系统。

项目的核心问题包括：

- 如何驱动模型在“理解目标、选择行动、调用工具、观察结果、继续迭代”之间形成稳定闭环；
- 如何统一管理模型调用、本地工具、执行权限、上下文和会话状态；
- 如何将一次 Agent 执行拆分为可查询的 Run、Step、Event 和 Artifact；
- 如何让 CLI、TUI 和 Web 共享同一个后台 Runtime 与事件协议；
- 如何为后续的中断恢复、上下文压缩、多 Agent 协作和安全隔离建立清晰边界。

因此，Vortex 的第一身份是 **Agent Runtime**，第二身份才是建立在 Runtime 之上的本地开发 Agent。项目价值不只体现在“能否完成代码任务”，还体现在执行过程是否清晰、状态是否可靠、权限是否可控，以及设计是否便于扩展和验证。

## 2. 项目原则

### 2.1 核心运行机制自主设计

Vortex 将自主定义 Agent Loop、运行状态机、事件模型、工具调用管道和会话模型。核心执行链路不会隐藏在通用 Agent 编排框架之后，以便完整理解并展示 Agent Runtime 的工作原理。

模型 SDK、Web 框架、数据库驱动、终端 UI 和可观测组件等基础设施使用成熟开源方案。项目不追求从零实现所有组件，而是把自主设计集中在最能体现 Agent 工程能力的部分。

### 2.2 Runtime 与客户端分离

Vortex Core 作为常驻后台进程负责执行任务、维护状态和产生事件。CLI、TUI 与 Web 是不同的客户端，不直接持有 Agent 的核心执行逻辑。

这种设计使前端退出不会改变 Runtime 的职责，也使多个交互端能够订阅同一份运行状态和事件数据。

### 2.3 状态与事件优先

Agent 执行不应只表现为一串对话消息。Vortex 将区分用户任务、具体运行、执行步骤、模型调用、工具调用、审批、事件和产物，使执行过程可以被持久化、查询和复盘。

所有重要状态变化都通过类型化事件表达。界面负责消费和展示事件，而不是从日志文本中猜测 Agent 当前处于什么状态。

### 2.4 权限控制与执行隔离分层

权限审批用于判断用户是否允许某项操作；执行隔离用于限制操作即使被允许后能够影响的范围。两者是不同的安全层，不能使用简单的命令正则或确认弹窗代替真正的执行边界。

### 2.5 先完成可靠闭环，再扩展能力数量

早期迭代先完成单 Agent 的内存运行闭环，再依次加入持久化、写操作权限与更完整的事件能力。项目不会以模型数量、工具数量或 Agent 角色数量作为早期目标。

## 3. 当前实现边界（v0.2.0）

Vortex 当前已经完成第一个纯内存单 Agent 纵向闭环：

```text
User Goal
  → AgentRuntime
  → DeepSeek native Tool Calling
  → Tool Registry / Executor
  → Workspace Observation
  → Next Model Iteration
  → Succeeded / Failed / Cancelled / Limit Reached
```

当前实现包括供应商无关的 Tool Call、Tool Result、Run Status 与 Runtime Event，自研有界 Agent
Loop，工作区受限的结构概览、目录浏览、分块文件读取和文本搜索工具，以及 TUI 工具过程展示。
只读工具执行前支持允许一次、允许当前会话和拒绝；会话允许项只保存在当前进程内。探索预算耗尽时，
Runtime 会关闭工具并要求模型基于已有 Observation 完成最佳总结。一次 Run 只有成功时才会把完整
消息链原子提交到当前进程历史。

当前模型能力由 Vortex 项目统一配置：默认模型为 DeepSeek V4 Flash，私有凭证固定从 Vortex
仓库根目录的 `.env` 加载，与启动时选择的 Agent 工作区相互独立。当前阶段不提供用户自带 API Key，
也不会读取业务工作区中的 `.env`。

当前不包含数据库、后台 Core、写文件、Shell、高风险执行隔离、持久化权限策略、上下文压缩、MCP、
多 Agent 和 Web。
以下架构描述是后续演进方向，不代表这些组件已经落地。

## 4. 长期目标架构

Vortex 长期保持模块化单体优先，目标架构主要由以下部分组成：

```text
CLI / TUI / Web
        │
        ▼
Vortex Core API
        │
        ├── Session & Run Management
        ├── Agent Runtime
        │     ├── Agent Loop
        │     ├── Context Builder
        │     ├── Model Adapter
        │     ├── Tool Runtime
        │     └── Policy & Approval
        ├── Event Stream
        └── Persistence
```

### Vortex Core

Vortex Core 是系统的控制中心，负责：

- 接收客户端创建会话、提交任务、取消运行和响应审批等请求；
- 创建并调度 Agent Run；
- 管理模型调用、工具执行和上下文构建；
- 持久化运行状态、事件和执行产物；
- 向 CLI、TUI 和 Web 推送实时事件。

### Agent Runtime

Agent Runtime 负责驱动一次任务从开始到结束。后续将扩展为更完整的显式状态机，目标状态包括：

```text
QUEUED
→ BUILDING_CONTEXT
→ CALLING_MODEL
→ EXECUTING_TOOL
→ RECORDING_OBSERVATION
→ SUCCEEDED / FAILED / CANCELLED
```

需要用户确认的工具调用可以进入 `WAITING_APPROVAL` 状态。每次状态变化都会产生对应事件，并在关键步骤保存可恢复所需的状态信息。

### Tool Runtime

所有工具通过统一注册表管理，并通过同一条调用管道执行：

```text
工具查找
→ 参数校验
→ 权限判断
→ 用户审批
→ 超时控制
→ 工具执行
→ 结果规范化
→ 事件与审计记录
→ Observation 回填
```

当前只提供文件读取、目录查看和文本搜索。后续可增加受控文件修改、Shell 执行和 Git 状态查看；工具数量保持克制，重点验证统一调用、错误处理和安全边界。

### Context Builder

未来的 Context Builder 负责根据当前任务和 Token 预算构造模型输入，并至少区分：

- 系统规则；
- 当前任务目标；
- 会话历史；
- 当前 Run 和 Step 状态；
- 最近的工具结果；
- 用户显式引用的工作区文件。

每次模型调用记录本次上下文由哪些部分组成，为后续实现上下文压缩、检索和质量分析保留基础。

## 5. 核心数据模型

长期围绕以下核心实体建模：

- **Workspace**：Agent 可以访问和操作的本地工作区；
- **Session**：用户与 Vortex 持续交互的会话；
- **Task**：用户希望完成的目标；
- **Run**：Task 的一次具体执行；
- **Step**：Run 中的一轮模型决策与行动；
- **ModelCall**：一次模型请求及其响应、Token 和耗时；
- **ToolInvocation**：一次工具调用及其参数、结果和状态；
- **Approval**：需要用户确认的操作及其处理结果；
- **RunEvent**：运行过程中发生的类型化事实；
- **Artifact**：工具输出、补丁、日志、摘要等执行产物。

Session、Task 和 Run 必须分离。同一个任务可以重新执行形成多个 Run；同一个 Session 也可以承载多个连续任务。

## 6. 基础技术选型

### 后端与 Agent Runtime

- **Python 3.12+**：作为核心开发语言；
- **asyncio**：承载模型流式响应、工具执行、事件推送和任务取消；
- **FastAPI**：提供 Core 控制接口和事件订阅接口；
- **Pydantic v2**：定义命令、事件、工具参数和模型适配协议；
- **uv**：管理 Python 依赖和开发环境。

### 数据持久化

- **PostgreSQL**：保存 Workspace、Session、Task、Run、Step、Event、Approval 等结构化数据；
- **SQLAlchemy 2**：数据访问与领域模型持久化；
- **Alembic**：数据库 Schema 迁移；
- **本地 Artifact 目录**：保存体积较大的工具输出、日志、补丁和其他执行产物，数据库只保存元数据与引用。

PostgreSQL 是运行状态的主要事实来源，内存状态只用于当前执行，不作为唯一存储。

### CLI、TUI 与 Web

- **Typer + Rich**：CLI 命令与基础流式输出；
- **Textual**：终端交互界面；
- **Next.js + React + TypeScript**：Web 管理界面；
- **REST**：创建会话、提交任务、取消运行、处理审批等控制操作；
- **Server-Sent Events（SSE）**：向不同客户端推送运行事件。

所有客户端共享同一套类型化事件语义，不分别实现 Agent Loop。

### 模型接入

Vortex 定义自己的 `ModelProvider` 抽象，对上层暴露统一的流式响应、工具调用、使用量和结束原因。当前只稳定接入一个模型供应商，同时提供可测试的 Fake Provider。

Runtime 内部不直接依赖某一家模型供应商的消息对象。供应商原始响应可以作为调试数据保存，但 Agent Loop 只处理 Vortex 定义的标准模型事件。

### 可观测性

后续可观测性同时保留两类数据：

- **RunEvent**：描述业务状态变化，用于界面展示、审计和运行回放；
- **OpenTelemetry Trace**：记录模型调用、工具执行、数据库操作和 API 请求的耗时与错误。

事件日志是 Agent 执行事实，Trace 是性能与调用链观测，两者不互相替代。

### 测试与质量

- **pytest + pytest-asyncio**：单元测试和异步集成测试；
- **Ruff**：代码检查与格式化；
- **mypy**：静态类型检查；
- **Fake Model / Fake Tool**：构造确定性测试，不依赖真实模型输出验证 Runtime 行为。

Agent Loop、状态转换、工具权限、事件顺序和失败处理必须能够在不调用真实模型 API 的情况下测试。

## 7. 长期演进目标

长期目标是形成一条完整且可观察的单 Agent 执行链路：

1. 用户通过 CLI、TUI 或 Web 创建 Session 并提交任务；
2. Vortex Core 创建 Task 和 Run，记录初始事件；
3. Context Builder 构造模型上下文；
4. 模型返回文本或结构化工具调用；
5. Tool Runtime 完成参数校验、权限判断和执行；
6. 工具结果作为 Observation 回填，Agent 继续下一轮；
7. Run 在成功、失败、取消或达到限制时结束；
8. 客户端可以实时查看模型调用、工具调用、审批和状态变化；
9. Run 结束后仍可查询历史步骤、事件、工具结果和执行产物。

后续逐步实现以下能力：

- 自研单 Agent Loop 与明确的终止条件；
- Session、Task、Run、Step 的基础管理；
- 模型流式输出和工具调用；
- 基础 Tool Registry 与统一调用管道；
- 工具权限分级和人工审批；
- 运行事件持久化与实时订阅；
- 基础上下文组装和 Token 使用记录；
- CLI/TUI 执行入口与基础 Web 观察页面；
- 取消、超时、错误分类和有限重试；
- 基于确定性 Fake Provider 的 Runtime 测试。

## 8. 当前非目标

为了保持核心清晰，当前不以以下内容为目标：

- 复刻 Claude Code 或 Codex 的完整产品体验；
- 为某个垂直行业构建业务助手；
- 支持大量模型供应商和大量工具；
- 开放式、多层递归的多 Agent 网络；
- 复杂知识库、向量检索和 RAG 平台；
- 多租户 SaaS、企业级权限和分布式部署；
- 完整 IDE 插件或浏览器自动化。

这些边界并不限制 Vortex 的长期扩展，而是确保每个阶段都形成结构清晰、运行可靠、可以深入解释的 Agent Runtime 基础。

## 9. 长期完成标准

当 Vortex 能够稳定演示以下完整场景时，可以认为长期基础架构基本成立：

> 用户从任意客户端提交一个本地工作区任务；Core 创建 Run 并持续输出类型化事件；模型读取必要文件、提出工具调用，受控工具在需要时请求审批；工具结果回填后 Agent 继续执行并最终结束；用户可以在 TUI 或 Web 查看完整时间线，并在任务结束后查询对应的 Step、事件、工具结果和产物。

项目的成功标准不是 Agent 能自动解决多复杂的问题，而是这条运行链路具有明确的数据模型、稳定的状态转换、可测试的执行行为和可追溯的过程记录。
