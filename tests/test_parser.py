if __name__ == "__main__":
    import _bootstrap

import pytest

from agent_runtime.parser import DecisionParseError, parse_decision


def test_parse_fenced_tool_call():
    decision = parse_decision(
        '```json\n{"type":"tool_call","name":"calculator","arguments":{"expression":"1+2"}}\n```'
    )
    assert decision.type == "tool_call"
    assert decision.name == "calculator"


def test_parse_json_surrounded_by_text():
    decision = parse_decision('结果如下 {"type":"final","answer":"你好"} 完成')
    assert decision.answer == "你好"


@pytest.mark.parametrize(
    "value",
    ["not json", "[]", '{"type":"final"}', '{"type":"tool_call","name":"x"}'],
)
def test_reject_invalid_decisions(value):
    with pytest.raises(DecisionParseError):
        parse_decision(value)


if __name__ == "__main__":
    raise SystemExit(_bootstrap.run(__file__))
