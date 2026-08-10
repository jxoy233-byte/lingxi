"""
code_fingerprint 模块单元测试

覆盖：
- 顶层入口：python / nodejs / javascript 三种 lang 路径
- 稳定性：参数值变化不影响 fingerprint
- 区分度：imports / function calls 差异会改 fingerprint
- 不变量：内置 / 关键字 / dunder 不污染 fingerprint
- aliases：py / node / js 归一化
- 边界：空 code / 不支持语言 → 返回空串
"""

import re
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[2]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from ChatMe.ChatWorkflow.mcps.code_fingerprint import (  # noqa: E402
    CODE_FP_PREFIX,
    SUPPORTED_LANGUAGES,
    _extract_function_calls,
    _extract_js_imports,
    _extract_python_imports,
    code_fingerprint,
)


# ---------------------------------------------------------------------------
# Python 路径
# ---------------------------------------------------------------------------


def test_python_fingerprint_basic():
    """基本：import + 调用 → fingerprint 包含对应模块/函数。"""
    args = {
        "code": "from Tavily import tavily_search\nresult = tavily_search('hello', max_results=8)\nprint(result)\n",
        "language": "python",
        "local": False,
    }
    fp = code_fingerprint(args)
    assert fp.startswith(CODE_FP_PREFIX)
    assert "lang=python" in fp
    assert "sandbox=1" in fp
    assert "imp=Tavily" in fp
    # print 是 builtin，应被过滤；tavily_search 是调用
    assert "fn=tavily_search" in fp
    assert "fn=print" not in fp


def test_python_fingerprint_parameter_change_does_not_affect():
    """参数值变化不改变 fingerprint。"""
    args1 = {
        "code": "from Tavily import tavily_search\ntavily_search('news1', search_depth='advanced', max_results=5)\n",
        "language": "python",
        "local": False,
    }
    args2 = {
        "code": "from Tavily import tavily_search\ntavily_search('completely different query')\n",
        "language": "python",
        "local": False,
    }
    assert code_fingerprint(args1) == code_fingerprint(args2)


def test_python_fingerprint_distinguishes_import_change():
    """import 不同 → fingerprint 不同。"""
    args1 = {
        "code": "from Tavily import tavily_search\ntavily_search('x')\n",
        "language": "python",
        "local": False,
    }
    args2 = {
        "code": "from Bocha import bocha_search\nbocha_search('x')\n",
        "language": "python",
        "local": False,
    }
    assert code_fingerprint(args1) != code_fingerprint(args2)


def test_python_fingerprint_distinguishes_function_call_change():
    """调用函数集不同 → fingerprint 不同。"""
    args1 = {
        "code": "import subprocess\nsubprocess.run(['ls'])\n",
        "language": "python",
        "local": False,
    }
    args2 = {
        "code": "import subprocess\nsubprocess.call(['ls'])\n",
        "language": "python",
        "local": False,
    }
    assert code_fingerprint(args1) != code_fingerprint(args2)


def test_python_fingerprint_sandbox_change():
    """local 改变 fingerprint（反向：local=False 对应 sandbox=1）。"""
    args1 = {"code": "x = 1\nprint(x)\n", "language": "python", "local": False}
    args2 = {"code": "x = 1\nprint(x)\n", "language": "python", "local": True}
    assert "sandbox=1" in code_fingerprint(args1)
    assert "sandbox=0" in code_fingerprint(args2)
    assert code_fingerprint(args1) != code_fingerprint(args2)


def test_python_fingerprint_filters_builtins():
    """builtins / keywords / dunder 不应出现在 fn 段。"""
    code = """
import re
class Foo:
    def __init__(self):
        self.x = 1
    def bar(self):
        return len(self.x) + int('1')
if __name__ == '__main__':
    for i in range(10):
        print(i)
"""
    fp = code_fingerprint({"code": code, "language": "python", "local": False})
    # filter set 里包含的字
    for forbidden in ("print", "len", "range", "int", "__init__", "__name__", "__main__", "if", "for", "self"):
        assert f"fn={forbidden}" not in fp, f"{forbidden} 应该被过滤"
    # 但自有调用 `bar` 保留
    assert "fn=bar" in fp


def test_python_alias_py_to_python():
    """`py` alias 归一化为 `python`。"""
    args = {"code": "import sys\nprint('x')\n", "language": "py"}
    fp = code_fingerprint(args)
    assert "lang=python" in fp


def test_python_extract_imports_with_dot():
    """`import X.Y.Z` → 顶层 X。"""
    imports = _extract_python_imports("import a.b.c\nfrom x.y import z\nimport p\n")
    assert imports == {"a", "x", "p"}


# ---------------------------------------------------------------------------
# nodejs 路径
# ---------------------------------------------------------------------------


def test_nodejs_fingerprint_basic():
    """nodejs：require + 调用 → 提取 module 名 + 调用函数。"""
    args = {
        "code": "const fs = require('fs');\nconst data = fs.readFileSync('/tmp/foo.txt', 'utf8');\nconsole.log(data);\n",
        "language": "nodejs",
        "local": False,
    }
    fp = code_fingerprint(args)
    assert "lang=nodejs" in fp
    assert "imp=fs" in fp
    # console.log / fs.readFileSync → fn 应有 readFileSync（console 是 nodejs builtin）
    assert "fn=readFileSync" in fp
    # console 是 Node 内置，不应出现
    assert "fn=console" not in fp


def test_nodejs_parameter_change_does_not_affect():
    """nodejs 下不同参数值同 fingerprint。"""
    args1 = {
        "code": "const fs = require('fs');\nfs.readFileSync('/tmp/a.txt', 'utf8');\n",
        "language": "nodejs",
        "local": False,
    }
    args2 = {
        "code": "const fs = require('fs');\nfs.readFileSync('/very/different/path.js', 'binary');\n",
        "language": "nodejs",
        "local": False,
    }
    assert code_fingerprint(args1) == code_fingerprint(args2)


def test_nodejs_alias_node_to_nodejs():
    """`node` alias 归一化为 `nodejs`。"""
    args = {"code": "const fs = require('fs');\nfs.readFileSync('x');\n", "language": "node"}
    fp = code_fingerprint(args)
    assert "lang=nodejs" in fp


def test_nodejs_es_module_imports():
    """nodejs ES module import 也支持。"""
    imports = _extract_js_imports("import fs from 'fs';\nimport { readFile } from 'fs/promises';\n")
    assert "fs" in imports
    assert "fs/promises" in imports


# ---------------------------------------------------------------------------
# javascript 路径
# ---------------------------------------------------------------------------


def test_javascript_fingerprint_basic():
    """javascript：es module + 浏览器 / 用户函数。"""
    args = {
        "code": "import { searchWeb } from './search';\nconst r = searchWeb('news');\nconsole.log(r);\n",
        "language": "javascript",
        "local": False,
    }
    fp = code_fingerprint(args)
    assert "lang=javascript" in fp
    # console / log 都是 JS globals
    assert "imp=./search" in fp
    assert "fn=searchWeb" in fp
    assert "fn=console" not in fp
    assert "fn=log" not in fp


def test_javascript_alias_js_to_javascript():
    """`js` alias 归一化为 `javascript`（**不**归一为 nodejs）。"""
    args = {"code": "const x = 1;\nconsole.log(x);\n", "language": "js"}
    fp = code_fingerprint(args)
    assert "lang=javascript" in fp
    # 确保不是 nodejs
    assert "lang=nodejs" not in fp


def test_javascript_vs_nodejs_distinct_globals():
    """javascript vs nodejs：调用同一个名字 `log` 时 javascript 应 filter 掉（属于 console.log），但用户自定义 `log` 仍出现。
    这里测：仅 fn=log 不在 lang=javascript 的 filter 里（用 console.log 触发）。"""
    args = {
        "code": "function customLog(msg) { return msg; }\ncustomLog('x');\n",
        "language": "javascript",
        "local": False,
    }
    fp = code_fingerprint(args)
    assert "fn=customLog" in fp


# ---------------------------------------------------------------------------
# 边界 / 失败路径
# ---------------------------------------------------------------------------


def test_empty_code_returns_empty():
    """空 code → 空 fingerprint。"""
    assert code_fingerprint({"code": "", "language": "python"}) == ""
    assert code_fingerprint({"code": "   \n  ", "language": "python"}) == ""


def test_unsupported_language_returns_empty():
    """不支持的语言（ruby 等） → 空 fingerprint。"""
    assert code_fingerprint({"code": "puts 'x'", "language": "ruby"}) == ""


def test_missing_language_defaults_to_python():
    """未传 language → python 默认。"""
    fp = code_fingerprint({"code": "x = 1\nprint(x)\n"})
    assert "lang=python" in fp


def test_supported_languages_set():
    """SUPPORTED_LANGUAGES 确实包含三种 sandbox 支持语言。"""
    assert "python" in SUPPORTED_LANGUAGES
    assert "nodejs" in SUPPORTED_LANGUAGES
    assert "javascript" in SUPPORTED_LANGUAGES
