# Vibe Coding 录屏测试用例

## 一、录屏目标

建议录制 6～10 分钟，重点证明以下能力：

- 使用真实 DeepSeek API。
- Agent 能自主选择直接回答或调用工具。
- 支持单工具与连续多工具调用。
- Session 能持久化并相互隔离。
- 支持纯对话追问和带工具追问。
- 有最大执行步数、Context 压缩、异常处理和 Trace。
- 自动测试可以执行并明确显示结果。

录屏时不要打开 `.env`，避免泄露 API Key。所有网页测试都使用新建 Session，不需要删除已有数据。

## 二、录屏前准备

在项目根目录打开两个 PowerShell 窗口。

窗口一启动网页：

```powershell
cd "D:\冲agent实习\练习\笔试题1"
python web.py
```

浏览器打开：

```text
http://127.0.0.1:8000
```

窗口二留作运行测试：

```powershell
cd "D:\冲agent实习\练习\笔试题1"
```

开始录屏前检查：

- 页面左下角显示 `Runtime Online` 和 DeepSeek 模型。
- 右侧 Trace 面板可见。
- 点击“新建 Session”，保证演示从空白会话开始。

## 三、网页验收用例

### WEB-01：直接回答

输入：

```text
你好，请用一句话介绍你自己
```

预期：

- Agent 直接回复，不调用工具。
- 右侧产生一个独立的消息事件组。
- 事件组包含 `RUN STARTED → MODEL DECISION → FINAL ANSWER`。
- `MODEL DECISION` 显示 `final`。

录屏说明：指出模型能够自主判断这个问题不需要工具。

### WEB-02：Calculator 单工具调用

输入：

```text
请准确计算 (125 + 75) * 3
```

预期：

- 最终答案为 `600`。
- 新消息拥有独立 Trace 卡片。
- Trace 至少包含 `MODEL DECISION → TOOL COMPLETED → FINAL ANSWER`。
- 工具名称为 `calculator`，工具结果成功。

录屏说明：展开讲解模型只负责决定工具和参数，实际表达式由安全 AST 计算器执行。

### WEB-03：Weather 与 Todo 连续调用

输入：

```text
查询北京天气，并帮我添加一个“出门带伞”的待办
```

预期：

- Agent 依次调用 `weather` 和 `todo`；具体先后由模型决定。
- 最终回答明确天气来自 mock 数据。
- 右侧 Session Memory 出现未完成待办“出门带伞”。
- 同一消息事件组中出现两次 `TOOL COMPLETED`。

录屏说明：这是最重要的基本 Loop 演示，说明工具结果回填给 DeepSeek 后，模型会继续决定下一步。

### WEB-04：纯对话追问

依次输入：

```text
请记住：我最喜欢的颜色是蓝色
```

```text
我最喜欢什么颜色？
```

预期：

- 第二次回答“蓝色”。
- 两条用户消息分别拥有独立 Trace 卡片。
- 第二次模型调用使用了当前 Session 的历史消息。

### WEB-05：带工具的追问

依次输入：

```text
计算 24 * 7
```

```text
把刚才的计算结果再加 32
```

预期：

- 第一次结果为 `168`。
- 第二次能够引用上次结果，并调用 calculator 计算 `168 + 32`。
- 第二次结果为 `200`。

录屏说明：证明 Agent 不仅能记住普通文本，还能基于上一轮工具结果继续调用工具。

### WEB-06：Session 隔离与恢复

当前窗口作为 Session A，确保其中已有：

```text
偏好：蓝色
待办：出门带伞
```

操作：点击左侧“新建 Session”，创建 Session B，然后输入：

```text
我最喜欢什么颜色？请同时列出我的待办
```

预期：

- Session B 不应知道“蓝色”。
- Session B 的 Todo 为空。

随后从左侧切回 Session A，输入：

```text
我最喜欢什么颜色？请列出我的待办
```

预期：

- 能回答“蓝色”。
- 能通过 todo 工具列出“出门带伞”。
- 刷新浏览器后 Session 和消息仍存在。

### WEB-07：工具异常处理

输入：

```text
请计算 1 / 0
```

预期：

- calculator 返回除零错误。
- Agent 给出可理解的错误说明。
- 网页服务不崩溃，仍可继续发送下一条消息。
- Trace 中 `TOOL COMPLETED` 标记失败及错误信息。

再输入：

```text
查询成都天气
```

预期：

- weather 返回 mock 数据不包含成都的错误。
- Agent 如实说明限制，不伪造实时天气。

### WEB-08：面板与可观测性

操作：

1. 拖动左侧栏右边缘，调整 Session 栏宽度。
2. 拖动右侧栏左边缘，调整 Trace 栏宽度。
3. 滚动中间聊天记录。
4. 刷新页面。

预期：

- 两侧宽度可调整，中间聊天区保持可用。
- 页面刷新后保留上次栏宽。
- 中间聊天区独立滚动。
- 每条用户消息的事件流由独立卡片隔开。

## 四、Context 压缩演示

默认阈值较大，不建议在录屏中发送几十条消息。可以临时在 `.env` 中加入：

```dotenv
AGENT_CONTEXT_CHARS=500
```

重启网页后，在新 Session 连续发送几条包含明确事实和较长内容的消息，再进行追问。

预期：

- Trace 出现 `CONTEXT COMPACTED`。
- 右侧 Session Memory 出现历史摘要。
- 最近消息仍保留原文。
- Agent 仍能回答摘要中的关键事实。

该演示结束后，建议恢复：

```dotenv
AGENT_CONTEXT_CHARS=24000
```

如果录屏时间有限，可以不操作网页压缩，直接运行 `tests/test_context.py` 证明压缩和失败降级路径。

## 五、自动测试录屏

### TEST-01：Context 测试

```powershell
python tests/test_context.py
```

预期：

```text
[PASS] Context 压缩后保留最近消息
[PASS] 摘要模型失败时执行降级压缩
```

### TEST-02：Runtime 测试

```powershell
python tests/test_runtime.py
```

预期覆盖：直接回复、工具回填、连续工具、格式修复、最大 step 和追问。

### TEST-03：Session 测试

```powershell
python tests/test_session.py
```

预期覆盖：持久化、窗口隔离、非法 ID 和损坏文件。

### TEST-04：全量测试

```powershell
python -m pytest
```

预期：所有本地测试通过，真实 API 测试默认显示一项 skipped。

### TEST-05：真实 DeepSeek API

```powershell
$env:RUN_REAL_LLM_TEST="1"
python tests/test_real_api.py
```

预期：

```text
1 passed
```

运行完成后清除临时变量：

```powershell
Remove-Item Env:RUN_REAL_LLM_TEST
```

## 六、推荐录屏顺序

```text
1. 简短展示 README 架构图和项目目录
2. 启动 web.py，打开网页
3. WEB-01 直接回答
4. WEB-02 calculator
5. WEB-03 weather + todo 连续工具
6. WEB-04、WEB-05 两类追问
7. WEB-06 Session 隔离与恢复
8. WEB-07 异常处理
9. WEB-08 页面交互与 Trace 分组
10. 终端运行全量测试
11. 单独运行真实 DeepSeek API 测试
```

录屏结束前展示：代码仓库地址、README、`docs/prompts.md` 和 `docs/development-log.md`，对应题目的全部提交要求。

