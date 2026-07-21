"""Make the assessment test output readable in demos and recordings."""


TEST_DESCRIPTIONS = {
    "test_parse_fenced_tool_call": "解析 Markdown 代码块中的工具调用 JSON",
    "test_parse_json_surrounded_by_text": "从附加文本中提取最终回答 JSON",
    "test_reject_invalid_decisions": "拒绝不符合 Agent 输出协议的数据",
    "test_calculator_is_safe": "计算器正确计算并阻止危险表达式",
    "test_tool_schema_validation_and_unknown_tool": "校验工具参数并处理未知工具",
    "test_duplicate_registration": "拒绝重复注册同名工具",
    "test_todo_belongs_to_session": "Todo 状态严格归属当前 Session",
    "test_tool_exception_is_returned_to_agent": "工具内部异常被包装并返回 Agent",
    "test_long_tool_output_is_truncated": "超长工具输出会被安全裁剪",
    "test_sessions_are_persistent_and_isolated": "Session 可以持久化且彼此隔离",
    "test_invalid_or_missing_session": "拒绝非法或不存在的 Session",
    "test_corrupt_session_is_reported": "识别损坏的 Session 文件",
    "test_context_compaction_keeps_recent_messages": "Context 压缩后保留最近消息",
    "test_compaction_has_fallback_when_llm_fails": "摘要模型失败时执行降级压缩",
    "test_direct_answer": "模型无需工具即可直接回答",
    "test_tool_result_returns_to_loop": "工具结果会回填并继续 Agent 循环",
    "test_multiple_tools_and_session_todo_persistence": "连续调用天气和 Todo 并持久化",
    "test_invalid_output_gets_one_repair": "非法模型输出触发一次格式修复",
    "test_max_steps_stops_infinite_tool_loop": "达到最大步数后阻止无限循环",
    "test_follow_up_contains_previous_history": "追问能够读取当前 Session 历史",
    "test_deepseek_is_default_provider": "默认模型供应商和模型为 DeepSeek",
    "test_serves_web_page_and_meta": "网页和 Runtime 元数据 API 可访问",
    "test_session_and_message_api": "网页 Session、消息和 Trace API 正常工作",
    "test_web_api_validates_input": "网页 API 拒绝非法消息输入",
    "test_real_api_returns_content": "真实 DeepSeek API 能够返回内容",
}


def _description(nodeid: str) -> str:
    parts = nodeid.split("::")
    if len(parts) < 2:
        return nodeid
    full_name = parts[-1]
    function_name = full_name.split("[")[0]
    description = TEST_DESCRIPTIONS.get(function_name, function_name)
    if "[" in full_name and full_name.endswith("]"):
        case = full_name[full_name.find("[") + 1 : -1]
        return f"{description}（输入用例: {case}）"
    return description


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    passed = [report for report in terminalreporter.stats.get("passed", []) if report.when == "call"]
    skipped = terminalreporter.stats.get("skipped", [])
    failed = [report for report in terminalreporter.stats.get("failed", []) if report.when == "call"]

    if passed:
        terminalreporter.write_sep("=", f"成功的测试（{len(passed)} 项）")
        for report in passed:
            terminalreporter.write_line(f"  [PASS] {_description(report.nodeid)}")
    if skipped:
        terminalreporter.write_sep("=", f"跳过的测试（{len(skipped)} 项）")
        for report in skipped:
            terminalreporter.write_line(f"  [SKIP] {_description(report.nodeid)}")
    if failed:
        terminalreporter.write_sep("=", f"失败的测试（{len(failed)} 项）")
        for report in failed:
            terminalreporter.write_line(f"  [FAIL] {_description(report.nodeid)}")
