
# Minimal Agent Runtime

一个不依赖 LangGraph、OpenHands 等 Agent 框架的最小可用 Agent。项目默认使用 DeepSeek，手写了模型调用、决策解析、工具注册、执行循环、Session、Context 压缩和 Trace，并提供完整网页工作台。

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
│  ├─ tools.py                    # 工具接口、注册中心、Schema 校验及四个工具实现
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

这里刻意使用模型输出 JSON 协议，而不是 SDK 的 Agent 或自动工具循环：Runtime 自己向模型提供工具 Schema、解析决策并执行工具，核心控制权完全在项目内。HTTP 层只负责一次 Chat Completions 请求。

## Session、Context 与 Memory

每个窗口对应独立 UUID，消息、摘要和 todo 保存到 `data/sessions/<id>.json`。不同 Session 不共享状态；切换或重启后可从文件恢复。Trace 存在 `data/traces/<id>.jsonl`，不会进入模型 Context。

Memory 分为两类：

1. 对话 Memory：每次调用模型前召回当前 Session 的摘要和最近消息，支持普通追问及带工具追问。
2. 结构化 Memory：todo 等确定性状态不依赖自然语言召回，工具执行时直接从当前 Session 读取和写入。

Context 超过字符阈值时，较早消息会被模型压缩成摘要，保留用户目标、事实、偏好、承诺、未完成事项和工具结论；最近 8 条消息保留原文。压缩 API 失败时使用基础截断摘要降级。完整思维链不进入 Context；只在 Trace 中保留模型自行返回的一句话决策摘要。

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

成功时应显示 `1 passed`；未设置 `RUN_REAL_LLM_TEST` 时显示 `1 skipped`。

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

## 建议录屏流程

1. 展示 `.env.example`、工具 Schema 和 Runtime 主循环。
2. 启动网页，在主界面询问计算问题，右侧 Trace 同步展示工具决策。
3. Session 1：查询北京天气并新增“带伞”待办，展示右侧 Memory。
4. 点击“新建 Session”创建 Session 2，让 Agent 协助写周报并新增另一个待办。
5. 从左侧分别切回两个 Session，追问上下文并检查待办，证明隔离与恢复。
6. 运行测试，展示通过结果。

录屏文件不直接提交到 Git：视频体积较大，已通过 `.gitignore` 排除。请上传到网盘、云盘或招聘方指定平台，并在最终提交说明中附可访问链接。

Prompt 见 [docs/prompts.md](docs/prompts.md)，AI 辅助开发和问题解决记录见 [docs/development-log.md](docs/development-log.md)，完整录屏步骤见 [docs/recording-test-cases.md](docs/recording-test-cases.md)。
