# AI Prompt 与问题解决记录

## 使用 AI 的范围

本项目使用 AI 辅助拆解题目、检查需求覆盖、设计测试矩阵和审阅边界情况。核心 Runtime、模型协议、工具执行、Session 持久化和 Context 管理均在项目源码中实现，没有引入 Agent 框架。

项目约定默认语言模型为 DeepSeek，当前默认模型为 `deepseek-v4-flash`，通过其 OpenAI-compatible Chat Completions API 调用。主要开发指令可概括为：

```text
阅读题目，规划一个 Python Web 最小 Agent。必须手写基本循环、工具注册和 Schema、模型输出解析、Session 隔离、Context 压缩、异常处理、Trace 与自动测试，并使用真实 OpenAI-compatible LLM API。
```

Web 层只负责 Session、消息和 Trace 的 HTTP API 与三栏工作台，不复制 Agent 逻辑；所有交互统一复用同一套 `AgentRuntime`、工具注册中心和持久化层。

## 关键问题与取舍

### 原生 function calling 还是自定义 JSON 协议

选择自定义 JSON 决策协议。这样可以明确展示“向模型提供 Schema—解析模型决定—执行工具—继续循环”的全部代码，也能适配更多 OpenAI-compatible 服务。代价是模型可能输出非法 JSON，因此加入代码块清理、嵌入 JSON 提取和一次纠正重试。

### 是否保存思考过程

只保存一句 `reasoning_summary` 到 Trace，不把详细思维链加入历史 Context。这样既满足决策可观测性，又避免无用推理消耗 Context 或影响后续回答。

### 工具结果怎样回填

内部消息使用 `tool` role 保存，但发往兼容接口时转换成带 `<tool_result>` 边界的 user 消息。这避免部分兼容服务要求原生 `tool_call_id` 的差异，同时仍清楚区分用户输入和执行观察。

### Session 如何隔离

使用每个 Session 一个 JSON 文件，并限制 Session ID 字符，阻止路径穿越。写入采用同目录临时文件加 `os.replace`，降低进程中断造成文件半写的风险。todo 是结构化 Session 状态，不从自然语言历史推测。

### Context 怎样压缩

达到阈值后只压缩较早消息，保留最近消息原文。模型摘要要求保留目标、事实、偏好、承诺、未完成事项和工具结论；API 失败时退化为确定性裁剪，保证对话仍能继续。Trace 与详细异常永不进入 Context。

### 怎样测试真实模型的不确定性

核心自动测试注入 Scripted LLM，精确控制模型每一步返回，稳定覆盖多工具和错误路径。另保留显式开启的真实 API smoke test，证明网络接口可用，但不把随机外部服务作为普通测试的前置条件。

## 已识别限制

- JSON Schema 校验器仅实现本项目需要的 required、基础类型、enum 和 additionalProperties；生产环境可替换为完整 JSON Schema 库。
- 文件存储适合单机演示；同一 Session 的多进程并发写入需增加文件锁或迁移数据库。
- 字符数只是 token 的低成本近似，生产环境应使用模型对应 tokenizer。
- mock 搜索和天气不代表实时结果，UI 与 README 都应明确展示这一点。
- 网页版使用标准库 HTTP Server，面向本机笔试演示；没有认证、TLS、限流和生产级多进程并发能力。
