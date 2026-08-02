# AGENTS.md

本文件是 Vortex 仓库的根级 Agent 开发指南，作用范围为整个仓库。开始工作前必须先阅读本文件，
再阅读任务直接涉及的代码和文档。

如果未来某个子项目需要不同规则，可以在对应目录添加更具体的 `AGENTS.md`。距离目标文件最近的
指南优先，但不得降低本文件中的安全、密钥保护和质量门禁要求。

## 1. 项目使命

Vortex 是面向本地工作区的 Agent Runtime 学习与工程实践项目，参考 Claude Code、Codex CLI、
KamaClaude、Toad 等产品或开源项目，但不复刻其界面、私有实现或完整功能。

项目重点展示：

- 显式 Agent Loop 与可解释的终止条件
- 模型与 Runtime 解耦的流式事件协议
- 统一 Tool Registry、权限审批和安全执行管道
- 上下文构建、Token 预算、压缩和关键信息保留
- Session、Task、Run、Step 和 Event 的清晰建模
- 中断、取消、超时、失败恢复和 Checkpoint
- Trace、成本、耗时、错误与运行回放
- MCP 和边界清晰的多 Agent 协作
- CLI/TUI 与 Web 对同一 Runtime 语义的消费

Vortex 不是垂直业务助手，也不是“模型 API + 聊天页面”。任何新增能力都应帮助项目理解、展示或
验证 Agent Runtime 的核心机制。

## 2. 当前事实

版本号以 `pyproject.toml` 为唯一事实来源。当前代码已经具备：

- Typer CLI 和 `vortex` 命令
- Textual TUI 欢迎与对话界面
- DeepSeek V4 Flash 默认接入
- OpenAI-compatible Chat Completions
- 异步流式文本、Token 用量和安全错误映射
- DeepSeek 原生流式 Tool Calling 与跨分片调用组装
- 默认关闭思考模式
- 当前进程内临时多轮历史
- 自研有界单 Agent Loop 与类型化 Runtime Event
- Tool Registry、统一 Executor 和 Observation 回填
- 工作区受限的 `list_directory`、`read_file`、`search_files`
- 面向大型仓库的 `workspace_overview` 与大文件连续分块读取
- 只读工具首次调用审批、允许一次/本会话/拒绝和进程内缓存
- 最大迭代、工具调用、工具超时和预算耗尽后的强制总结
- TUI 工具调用、结果预览、耗时和结束状态展示
- TUI 选区复制、复制/取消动态路由和 macOS 剪贴板兼容
- Textual MarkdownStream 增量 GFM 渲染
- 生成取消与输入状态恢复
- Fake Provider、Fake Tool、MockTransport 和无头 TUI 测试
- 项目代码采用 MIT License

当前尚未实现：

- 文件修改、Shell 执行、持久化权限策略与执行沙箱
- 持久化 Session、Task、Run、Step 和 Event
- 上下文压缩、长期记忆和检索
- MCP、多 Agent、FastAPI Core 和 Web Console

不要在 README、界面或代码注释中把规划能力描述成已经完成。

## 3. 目录与职责

```text
src/vortex/
├── cli/            Typer 命令、参数和非交互入口
├── tui/            Textual App、Screen、Widget 和 TCSS
├── config/         环境变量、配置默认值和配置验证
├── domain/         供应商无关的消息、事件和值对象
├── providers/      ModelProvider 协议、模型适配器和错误归一化
├── runtime/        单 Agent Loop、运行限制与内存状态提交
├── tools/          工具定义、Schema、Registry 和调用管道
└── permissions/    风险分级、Policy 和 Approval
```

`persistence`、`protocol`、`api` 和 Web 等规划模块只在开始实现对应纵向能力时创建，不保留空
目录或无行为的占位类。

当前数据流：

```text
Input
  → WelcomeScreen
  → AgentRuntime
  → ModelProvider / ToolExecutor
  → DeepSeekProvider / ToolRegistry
  → RuntimeEvent
  → MarkdownStream / ToolCallView / TUI status
```

模块边界要求：

- `domain` 不得导入 OpenAI、DeepSeek、Textual、数据库或 Web 框架类型
- `runtime` 只依赖领域对象和抽象协议，不直接访问供应商 SDK
- `providers` 负责请求转换、流解析、结束原因、用量和错误归一化
- `tui` 负责交互和事件展示，不负责拼装供应商请求
- `config` 不得创建 UI，也不得包含业务执行逻辑
- 预留目录只有在对应里程碑开始后才能加入真实实现

## 4. 架构原则

### 4.1 自主 Runtime

核心 Agent Loop、状态机、上下文构建、工具管道和事件模型由 Vortex 自主设计。不要将 LangGraph、
OpenAI Agents SDK 等编排框架引入核心执行路径，除非任务明确要求做隔离的对比实验。

基础设施可以使用成熟库，例如模型 SDK、数据库驱动、Web 框架和 OpenTelemetry。使用第三方库时
必须明确它解决的基础设施问题，不能让它隐藏 Vortex 需要展示的核心机制。

### 4.2 类型化边界

- 供应商原始对象必须在 Provider 层转换为 Vortex 领域对象
- 重要状态变化使用类型化事件，不使用松散字典或日志字符串代替
- 公共接口必须完整标注类型并通过 mypy strict
- 避免 `Any`、无边界 `dict[str, object]` 和跨层传递 SDK 对象
- 值对象优先使用 `dataclass(frozen=True, slots=True)` 或明确的 Pydantic 模型

### 4.3 异步与取消

- 模型流、工具执行、事件订阅和外部 I/O 使用异步接口
- 不得在 Textual 事件循环中执行阻塞网络或长时间同步操作
- `asyncio.CancelledError` 必须继续传播，不能被通用异常处理吞掉
- 清理网络流、Worker 和临时资源时使用 `try/finally`
- 取消、超时、失败和达到上限是正式终止状态，不是附属日志

### 4.4 状态提交

- 当前 `AgentRuntime` 仅在 Run 成功后原子提交用户消息、工具调用、Observation 与最终回复
- 失败或取消的模型文本可用于 UI 展示，但不得自动进入下一轮上下文
- 未来持久化后，完整会话记录、模型上下文和长期记忆必须保持概念分离
- 不要把数据库中的全部历史无条件发送给模型

### 4.5 事件优先

Runtime 围绕 `RuntimeEvent` 驱动客户端更新。事件表示已经发生的事实，必须具备稳定类型、顺序
和关联标识。日志用于调试，Trace 用于调用链与性能分析，两者都不能代替领域事件。

## 5. 模型 Provider 规范

默认 Provider 是 DeepSeek，默认模型是 `deepseek-v4-flash`。

当前约束：

- 使用 Chat Completions 作为首期稳定通信协议
- 使用 `AsyncOpenAI` 访问 DeepSeek OpenAI-compatible API
- 显式设置 `stream=True`
- 显式设置 `stream_options.include_usage=True`
- 显式关闭思考模式
- 正确处理 `choices=[]` 的最终 usage 分片
- 供应商异常转换为不泄露响应正文和密钥的 `ModelError`
- 已经输出部分文本后不得盲目自动重试，以免重复内容

新增 Provider 时：

1. 实现 `ModelProvider` 协议
2. 将供应商角色、流事件、用量和结束原因转换为 Vortex 类型
3. 不修改 Runtime 来识别供应商特有类型
4. 使用 MockTransport 或 Fake Client 编写无网络协议测试
5. 真实 API 测试只能是显式 opt-in，不得进入默认测试套件

## 6. TUI 规范

- 所有终端可见文案使用英文
- 保留用户确定的 Vortex Logo，除非任务明确要求修改
- 普通用户输入和错误信息按纯文本渲染
- 模型回复使用 Textual `Markdown.get_stream()` 增量渲染
- 不要为每个 Token 调用 `Markdown.update()` 重绘全文
- 生成期间界面必须继续响应取消、退出和窗口变化
- 输入框在成功、失败和取消后必须恢复可用与焦点
- 自动滚动使用 anchor 语义，用户主动上滚后不要强制拉回底部
- 新增布局必须同时考虑窄终端行为
- 不得为了视觉效果引入另一套与 Textual 重叠的交互框架

流式 Markdown 需要测试跨分片语法，例如拆开的强调标记、标题、代码围栏和表格分隔行。不得只用
完整字符串测试最终 Markdown。

## 7. 配置与密钥安全

- 仓库根目录 `.env` 是 Vortex 当前阶段绑定的私有模型配置，永远不得提交
- 配置路径不得根据 Agent 工作区或 current working directory 改变
- 当前阶段不读取工作区 `.env`，也不允许 Shell 同名变量覆盖项目提供的模型凭证
- `.env.example` 只包含变量名和安全默认值
- 不得读取、打印、记录、截图或回显用户的真实 API Key
- API Key 使用 `SecretStr` 等安全类型
- 用户错误信息不得包含请求头、响应正文、SDK repr 或内部堆栈
- 代码和测试中只能使用明显的假密钥，例如 `test-key`
- 默认测试必须注入假配置或 Fake Provider，不得加载仓库真实 `.env`
- 提交前搜索常见密钥模式，并确认 `.gitignore` 仍覆盖 `.env` 与 `.env.*`

如果密钥曾出现在聊天、日志或提交历史中，应建议用户立即轮换，不能仅依赖删除本地文件。

## 8. Python 编码规范

- Python 版本为 3.12+
- 行宽为 100，格式以 Ruff 为准
- 所有源码和测试必须通过 mypy strict
- 导入顺序交给 Ruff 检查
- 优先使用标准库和现有依赖，新增依赖前说明必要性
- 公共模块、类和复杂行为应有简洁 docstring
- 中文注释只用于解释关键边界、协议陷阱或非显然决策
- 注释保持简短，不逐行翻译代码，不使用句号结尾
- 终端文案、错误提示和命令帮助统一使用英文
- 不保留失效分支、伪实现、未使用兼容层或无任务依据的抽象

异常处理要求：

- 捕获尽可能具体的异常
- 通用异常只能位于进程或 UI 边界，并转换成安全提示
- 不允许静默吞掉异常
- 保留异常链 `raise ... from exc`
- 资源清理不能依赖正常完成路径

## 9. 测试规范

默认测试不得访问网络、消耗 Token 或依赖真实用户配置。

权限测试必须验证允许一次、本会话缓存、拒绝、无客户端时默认拒绝和取消传播。测试注入 Provider
不代表可以绕过 Runtime 权限管道。

测试层次：

- Domain/Runtime：使用确定性 Fake Provider 验证事件与状态
- Provider：使用 `httpx.MockTransport` 验证请求体和 SSE 解析
- TUI：使用 Textual `run_test()` 验证焦点、输入、取消和渲染结构
- Live smoke test：仅在用户显式配置并主动运行时执行

每个新增行为至少覆盖：

- 正常路径
- 供应商或工具失败
- 用户取消
- 边界输入或空结果
- 关键事件顺序或状态提交条件

不要只断言内部字段。TUI 问题应尽量验证真实渲染节点或行，协议问题应验证真实请求结构和分片顺序。

## 10. 必须通过的质量门禁

在交付代码前运行：

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
uv lock --check
```

涉及打包、入口、资源文件或依赖时额外运行：

```bash
uv build --no-sources
uv run vortex --version
```

涉及 TUI 布局时，除了无头测试还应执行一次真实尺寸或截图验证。测试通过不能单独证明视觉正确。

## 11. 依赖与构建

- `pyproject.toml` 是包元数据和工具配置的事实来源
- `uv.lock` 必须与 `pyproject.toml` 同步提交
- 使用 `uv sync` 同步开发环境
- 使用 `uv run` 执行项目内命令
- 不手动修改 `.venv` 中的包
- 不提交 `dist/`、缓存、IDE 文件或本地环境文件
- 不随意提高最低 Python 版本或扩大依赖版本范围

新增依赖前回答：

1. 标准库或现有依赖是否已经能够解决
2. 该依赖属于基础设施还是隐藏核心 Runtime
3. 是否维护活跃、类型支持良好且许可证可接受
4. 是否增加不必要的安装体积或平台限制
5. 是否需要新的错误、安全和测试边界

## 12. 开发流程

开始任务时：

1. 阅读本文件和任务相关文档
2. 检查当前工作区，不覆盖用户已有改动
3. 从当前代码事实推导最小完整改动范围
4. 先定义验收行为，再修改实现

实现过程中：

1. 保持提交范围聚焦
2. 优先扩展现有抽象，不并行创建重复体系
3. 同步编写测试和必要文档
4. 发现现有设计与任务冲突时先说明证据和取舍

结束任务前：

1. 对照用户要求逐项审计
2. 运行对应质量门禁
3. 检查是否泄露密钥或加入生成文件
4. 说明完成内容、验证证据和仍存在的真实限制

## 13. Git 与提交建议

- 一个提交聚焦一个可以说明的工程目的
- 推荐使用 Conventional Commits，例如 `feat:`, `fix:`, `test:`, `docs:`, `refactor:`
- 不提交 `.env`、`.venv`、缓存、构建产物和 IDE 配置
- 不通过重置、覆盖或删除来处理不属于当前任务的用户改动
- 提交信息描述“为什么改变”，避免只有“update files”

## 14. 当前迭代优先级

在没有新设计决策前，建议按以下顺序演进：

1. 稳定当前模型通信、Markdown 和 TUI 交互
2. 增加基础斜杠命令与模型配置
3. 为写文件和 Shell 建立风险分级、权限审批与执行隔离
4. 增加 Trace、完整 Run/Step/Event 记录与任务回放
5. 再建设持久化会话和 Context Builder
6. 最后扩展 MCP、多 Agent、后台 Core 和 Web

不要为了目录已经存在就提前实现数据库、FastAPI、Redis、Web 或复杂多 Agent 编排。

## 15. 参考规范

- [AGENTS.md open format](https://agents.md/)
- [Textual documentation](https://textual.textualize.io/)
- [Textual Markdown](https://textual.textualize.io/widgets/markdown/)
- [DeepSeek API documentation](https://api-docs.deepseek.com/zh-cn/)
- [uv documentation](https://docs.astral.sh/uv/)
- [Ruff documentation](https://docs.astral.sh/ruff/)
- [mypy documentation](https://mypy.readthedocs.io/)
- [pytest documentation](https://docs.pytest.org/)

参考优秀项目时应学习其问题拆分、边界和验证方法，不应无条件复制架构、依赖或产品功能。

本地更新命令：uv tool install --editable . --force --reinstall
