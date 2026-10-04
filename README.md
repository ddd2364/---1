
# Minimal Agent Runtime

一个不依赖 LangGraph、OpenHands 等 Agent 框架的最小可用 Agent。项目默认使用 DeepSeek，手写了模型调用、决策解析、工具注册、执行循环、Session、Context 压缩和 Trace，并提供完整网页工作台。

实现按 `learn-claude-code` 的教学风格组织：直观循环、普通工具函数、Schema 清单与分发映射。保留必要的 Session、HTTP、存储边界，便于逐个文件阅读和测试。

## 题目要求与实现

| Vibe Coding 要求 | 实现入口 | 验证 |
|---|---|---|
| 自行实现基本 Loop，直接回答或工具调用 | `AgentRuntime.agent_loop()` | 直接回答、连续工具、最大步数测试 |
| calculator、search 及自定义工具 | `tools.py` 的 `run_calculator/search/weather/todo` | AST 安全计算、mock 标记、待办状态 |
| 名称、描述、参数 Schema、注册机制 | `TOOLS` + `TOOL_HANDLERS` + `register(schema, handler)` | Schema 校验、未知工具和异常测试 |
| LLM 自主决策及输出解析 | `parse_decision()` 解析 JSON 中的决策摘要、调用或答案 | 非法输出修复；真实 API 工具闭环 |
| 双窗口独立 Session、持久化和追问 | 独立 UUID、JSON 文件与每会话线程锁 | 天气/周报双窗口，恢复后完成原待办 |
| Context、基础压缩和 Memory | 每步调用前检查；摘要 + 最近消息 + 当前待办 | 连续工具期间压缩、调用结果配对测试 |
| 基本异常和 Trace | 限次格式修复、HTTP 退避；JSONL 事件 | 参数、结果、耗时、失败原因可查看 |

建议阅读顺序：`tools.py → parser.py → runtime.py → context.py → session.py → llm.py`。

参考代码对应：s01 的循环、s02 的工具分发、s03 的执行前校验、s08 的压缩边界、s09 的 Memory 召回、s10 的提示组装、s11 的限次重试。题目未要求 Skills、Subagent 或 Worktree，因此没有扩展这些机制。

## 快速开始

要求 Python 3.10+（推荐 3.12）。运行时没有第三方依赖；测试使用 pytest。

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

编辑 `.env`，填入真实的 DeepSeek API Key：

```dotenv
DEEPSEEK_API_KEY=your-key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
```

启动网页版：

```powershell
python web.py
```

浏览器打开 `http://127.0.0.1:8000`。页面左侧新建和切换 Session，中间对话，右侧查看实时 Trace、Context 摘要与待办。服务监听地址可调整：

```powershell
python web.py --host 127.0.0.1 --port 8080
```

## 项目结构

```text
笔试题1/
├─ web.py                         # 网页版启动入口，创建 DeepSeek Client、Runtime 和 HTTP Server
├─ pyproject.toml                 # Python 项目元数据、可选测试依赖、Web 命令和 pytest 配置
├─ .env.example                   # DeepSeek Key、模型、最大 step 和 Context 阈值配置示例
├─ .gitignore                     # 排除密钥、Session 数据、缓存、虚拟环境和编辑器配置
├─ README.md                      # 运行方式、系统设计、Memory、测试和录屏说明
├─ 架构设计题答案.md              # 五个架构设计模块的作答内容
│
├─ web/                           # 浏览器前端，不包含 Agent 业务逻辑
│  ├─ index.html                  # 三栏工作台的页面结构和无障碍标签
│  ├─ styles.css                  # 视觉样式、响应式布局、滚动区和可拖拽栏宽
│  └─ app.js                      # Session、聊天、Trace、Memory 和面板交互
│
├─ agent_runtime/                 # 从零实现的 Agent 核心
│  ├─ __init__.py                 # 对外导出 AgentRuntime、RunResult 和 SessionStore
│  ├─ web.py                      # HTTP API、静态资源服务和 Web 服务启动逻辑
│  ├─ runtime.py                  # Agent 主循环、最大 step、工具执行和异常边界
│  ├─ llm.py                      # DeepSeek OpenAI-compatible HTTP 客户端和 .env 加载
│  ├─ parser.py                   # 解析 tool_call / final JSON，处理非法模型输出
│  ├─ tools.py                    # TOOLS、TOOL_HANDLERS、Schema 校验与四个 run_* 函数
│  ├─ session.py                  # Session 创建、加载、原子保存、恢复与隔离
│  ├─ context.py                  # Context 组装、工具结果回填、摘要压缩和降级机制
│  ├─ trace.py                    # 按 Session 写入 JSONL 执行事件日志
│  └─ models.py                   # Message、Session、Todo、ToolResult 等数据结构
│
├─ tests/                         # pytest 自动测试
│  ├─ conftest.py                 # 测试结果中文说明和成功/跳过/失败汇总
│  ├─ _bootstrap.py               # 支持直接运行单个 test_*.py 文件
│  ├─ test_runtime.py             # 直接回答、工具循环、多工具、追问和最大 step
│  ├─ test_tools.py               # 工具安全、Schema、异常、输出裁剪和 Todo 隔离
│  ├─ test_session.py             # Session 持久化、隔离、非法 ID 和损坏文件
│  ├─ test_context.py             # Context 压缩、最近消息保留和失败降级
│  ├─ test_parser.py              # JSON、代码块、附加文本和非法输出解析
│  ├─ test_llm.py                 # DeepSeek 默认地址和模型配置
│  ├─ test_web.py                 # 网页资源、Session、消息、Trace 和参数校验 API
│  └─ test_real_api.py            # 显式开启后调用真实 DeepSeek API 的 smoke test
│
└─ docs/                          # 提交与说明材料
   ├─ prompts.md                  # Agent、格式修复和 Context 压缩 Prompt
   ├─ development-log.md          # AI 辅助过程、问题、取舍和已知限制
   └─ recording-test-cases.md     # 网页与终端录屏测试用例及预期结果
```

运行时会自动创建 `data/sessions/` 和 `data/traces/`，分别保存 Session 状态和 Trace；它们属于本地数据，已被 `.gitignore` 排除。

## 系统设计

```text
Web UI
 └─ HTTP API：Session、消息、Trace、静态页面
    └─ AgentRuntime.run(session_id, input)
     ├─ SessionStore：加载/原子保存独立 Session
     ├─ ContextManager：系统 Prompt + Schema + 摘要 + 最近消息
     ├─ LLMClient：真实 DeepSeek OpenAI-compatible HTTP API
     ├─ DecisionParser：tool_call / final JSON
     ├─ ToolRegistry：Schema 校验与异常边界
     │   ├─ calculator
     │   ├─ search (mock)
     │   ├─ weather (mock)
     │   └─ todo (Session scoped)
     └─ TraceLogger：独立 JSONL 执行日志
```

每个用户请求最多执行 8 个 step。模型可以直接返回 final，也可以调用工具；工具结果作为明确标记的 `tool_result` 回填，下一个 step 由模型决定继续调用工具还是回答。非法模型输出只纠正一次，防止隐藏的无限重试。

`run()` 负责锁定 Session、加载和保存用户输入；`agent_loop()` 明确执行以下步骤：

```text
检查并压缩旧 Context → 组装 Prompt/Schema/Memory → 请求 LLM → 解析决策
    ├─ final：保存答案并返回
    └─ tool_call：保存调用参数 → Schema 校验 → handler(**arguments)
                  → 保存工具结果与 Trace → 下一步
```

每次工具执行的参数和结果成对保存；`reasoning_summary` 仅记录在 Trace。HTTP 网络/超时、429 和指定服务端错误最多重试 2 次，带指数退避和抖动；鉴权等其他 HTTP 错误直接返回。格式修复、压缩及网络重试属于辅助调用，不计入 8 个决策 step，均有自己的终止边界。

这里刻意使用模型输出 JSON 协议，而不是 SDK 的 Agent 或自动工具循环：Runtime 自己向模型提供工具 Schema、解析决策并执行工具，核心控制权完全在项目内。HTTP 层只负责一次 Chat Completions 请求。

## Session、Context 与 Memory

每个窗口对应独立 UUID，消息、摘要和 todo 保存到 `data/sessions/<id>.json`。不同 Session 不共享状态；切换或重启后可从文件恢复。Trace 存在 `data/traces/<id>.jsonl`，不会进入模型 Context。

同一服务进程中，同一 Session 的整轮请求串行执行，锁覆盖加载、工具执行和保存；不同 Session 可以并行。锁归属于共享的 `SessionStore`，不提供跨进程文件锁。

Memory 分为两类：

1. 对话 Memory：每次调用模型前召回当前 Session 的摘要和最近消息，支持普通追问及带工具追问。
2. 结构化 Memory：每次请求 LLM 前，将当前 Session 最近 20 条 todo（每条文本最多 120 字符）及总数注入 `<session_memory>`；完整数据保存在 Session，查询或修改时通过 todo 工具读取和写入。压缩不会删除待办。

每个决策 step 之前检查 Context，超过字符阈值时将较早消息压缩成摘要，保留用户目标、事实、偏好、承诺、未完成事项和工具结论；最近 8 条消息保留原文。切口落在工具结果上时多保留对应的调用，避免拆开。压缩 API 失败时使用本地截断摘要降级。完整思维链不进入 Context；Trace 只保留模型自行返回的一句话决策摘要。

系统协议和工具 Schema 放在 system 消息；历史摘要、当前待办作为明确标记的 user 数据消息放在最近历史之前，不把记忆内容提升为系统指令。每次只召回指定 Session，未实现跨会话用户画像或向量检索。

这里的字符阈值是**压缩触发阈值**，不是整个 API 请求的硬上限；系统提示、Schema 和额外注入的 Memory 不计入该估算。近期消息或单条用户输入本身过大时仍可能超过模型窗口，API 错误会明确返回，当前版本不丢弃本轮问题来强行满足预算。

可通过环境变量调节：

```dotenv
AGENT_MAX_STEPS=8
AGENT_CONTEXT_CHARS=24000
```

## 工具与安全边界

- `calculator` 使用受限 Python AST，只允许数字和基础算术运算，不调用 `eval`。
- `search` 和 `weather` 是确定性 mock，结果带 `mock: true`，方便离线演示和测试。
- `todo` 支持 `add`、`list`、`complete`，始终操作当前 Session。
- 注册中心统一校验 required、基础类型、enum 和额外参数，并把工具异常转换为结果交回 Agent。
- 工具输出限制长度，避免一次调用挤爆 Context。

新增工具只需编写普通函数并注册，无需继承工具基类：

```python
def run_echo(text: str, *, context: ToolContext) -> ToolResult:
    return ToolResult(ok=True, data=text)

registry.register({
    "name": "echo", "description": "返回输入文本",
    "parameters": {"type": "object", "properties": {"text": {"type": "string"}},
                   "required": ["text"], "additionalProperties": False},
}, run_echo)
```

## 测试

运行完整测试集：

```powershell
python -m pytest
```

默认使用详细输出：执行过程中逐条显示测试名称和 `PASSED/SKIPPED`，结束后以中文列出所有成功、跳过或失败的验证项。自动测试使用 Scripted/Fake LLM，覆盖直接回答、连续工具调用、格式修复、最大 step、Session 隔离、持久化、追问、压缩及异常。

每个测试文件也可以直接运行：

```powershell
python tests/test_runtime.py
python tests/test_tools.py
python tests/test_session.py
python tests/test_context.py
python tests/test_parser.py
python tests/test_llm.py
python tests/test_web.py
```

真实 DeepSeek API 测试默认跳过，配置 `.env` 后显式运行：

```powershell
$env:RUN_REAL_LLM_TEST="1"
python tests/test_real_api.py
```

包含“接口返回内容”和“真实模型选择 calculator 并回答 600”两项测试，成功时显示 `2 passed`；未开启时显示 `2 skipped`。故障排查时可用 `python -m pytest tests/test_real_api.py --tb=line` 输出简短错误，避免打印第三方库请求栈。

本次改造验证：44 项离线测试通过，另有 2 项真实 DeepSeek API 测试通过。真实工具闭环使用临时 Session，不修改现有聊天数据。

## 网页 API

```text
GET  /api/meta                         模型、工具和最大 step
GET  /api/sessions                     Session 列表
POST /api/sessions                     新建 Session
GET  /api/sessions/{id}                Session 消息与 Memory
POST /api/sessions/{id}/messages       发送消息并运行 Agent
GET  /api/sessions/{id}/traces         执行 Trace
```

API 与 Runtime 分离：网页不直接操作 Session 文件或工具，所有状态都经过后端统一处理。服务默认只监听本机地址；当前版本面向笔试演示，不包含登录鉴权，不应直接暴露到公网。







Prompt 见 [docs/prompts.md](docs/prompts.md)，AI 辅助开发和问题解决记录见 [docs/development-log.md](docs/development-log.md)，完整录屏步骤见 [docs/recording-test-cases.md](docs/recording-test-cases.md)。
