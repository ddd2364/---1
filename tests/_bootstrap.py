"""Support running an individual test file with `python tests/test_x.py`."""

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def run(test_file: str) -> int:
    try:
        import pytest
    except ModuleNotFoundError:
        print("无法运行测试：当前 Python 环境没有安装 pytest。", file=sys.stderr)
        print(f'请执行：& "{sys.executable}" -m pip install pytest', file=sys.stderr)
        return 2

    return pytest.main([test_file, "-v", "-ra"])
