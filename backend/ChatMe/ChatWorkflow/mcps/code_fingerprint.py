"""
code 工具语义指纹提取（用于永久批准的 pattern 精确匹配）

设计要点：
- 目的：解决"code 工具每次参数微变（如搜索词不同）就被重批"的痛点。Code 是一次性沙箱跑一段代码，
  完整 args JSON dump 做 fnmatch 几乎不会命中——这里提取 import 模块集 + 调用函数集 + lang/sandbox
  组成 fingerprint，相同结构视为同一调用意图。
- 匹配语义：**精确相等**（不用 fnmatch glob），避免 `code_fp:*` 把所有 code 都放行。
- 不变量：
  - 同 fingerprint = 同样 import 模块集 + 同样函数调用名集 + 同样 language + 同样 use_sandbox
  - 不含：参数值、变量名、注释、空白差异
- 支持语言：当前 sandbox 支持 python / nodejs / javascript（js）。
  - python / nodejs / javascript 三者作为独立 lang 字段持久化（filter globals 各自不同）：
    - python: filter _PY_BUILTINS_KW（builtins + keywords + dunder）
    - nodejs: filter _NODE_GLOBALS_KW（Node.js globals + Node 核心模块常量如 require/Buffer/process）
    - javascript: filter _JS_GLOBALS_KW（ECMAScript globals + 浏览器全局如 console/window/document）
  - 别名归一化：`py` → python；`node` → nodejs；`js` → javascript
  - 未知语言返回空字符串（不写 fingerprint，避免误匹配）。

安全：
- code 工具本身跑在 sandbox（默认）/ docker 池，由 CodeSandboxPool + platforms 包住；
- sub-tools（如 Tavily / Bocha / shell exec）自己有审批拦截；
- 这里 fingerprint 持久化做的是"用户已审查过类似代码结构"的持久化，粒度合理。
"""

from __future__ import annotations

import re
from typing import Set


# 持久化 pattern 的前缀：在 approved_commands list 里区分 cmd（glob）和 code（fingerprint）两类
CODE_FP_PREFIX = "code_fp:"


# ---------------------------------------------------------------------------
# Python 标识符过滤（builtins + keywords + dunder + self/cls）
# ---------------------------------------------------------------------------

_PY_BUILTINS_KW = frozenset({
    # builtins
    "print", "open", "range", "len", "int", "str", "list", "dict", "set", "tuple",
    "isinstance", "getattr", "setattr", "type", "super", "enumerate", "zip", "map",
    "filter", "sum", "min", "max", "abs", "round", "sorted", "reversed", "all", "any",
    "repr", "hash", "id", "iter", "next", "bool", "float", "bytes", "object",
    "staticmethod", "classmethod", "property", "hasattr", "delattr", "callable",
    "format", "input", "globals", "locals", "vars", "dir", "ord", "chr",
    "bin", "hex", "oct", "pow", "divmod", "complex", "frozenset", "bytearray",
    "memoryview", "ascii", "breakpoint", "exec", "eval", "__import__",
    # 常见 __dunder__
    "__init__", "__name__", "__main__", "__file__", "__doc__", "__dict__",
    "__class__", "__module__", "__str__", "__repr__", "__iter__", "__next__",
    "__len__", "__getitem__", "__setitem__", "__contains__", "__call__",
    # 常用 self/cls
    "self", "cls",
    # Python 关键字
    "if", "for", "while", "with", "try", "except", "finally", "def", "return",
    "yield", "raise", "pass", "continue", "break", "import", "from", "as", "in",
    "is", "not", "and", "or", "lambda", "True", "False", "None", "global", "nonlocal",
    "assert", "del", "elif", "else", "async", "await",
})


# ---------------------------------------------------------------------------
# 浏览器 JavaScript globals（`javascript` lang 字段用）
# ---------------------------------------------------------------------------

_JS_GLOBALS_KW = frozenset({
    # ECMAScript builtins
    "console", "log", "undefined", "NaN", "Infinity", "isNaN", "isFinite",
    "parseInt", "parseFloat", "encodeURI", "decodeURI", "encodeURIComponent",
    "decodeURIComponent", "setTimeout", "setInterval", "clearTimeout",
    "clearInterval", "Promise", "Symbol", "Proxy", "Reflect", "JSON", "Math",
    "Date", "Object", "Array", "Function", "Boolean", "Number", "String",
    "RegExp", "Error", "TypeError", "RangeError", "SyntaxError", "Map", "Set",
    "WeakMap", "WeakSet", "ArrayBuffer", "DataView", "Float32Array",
    "Float64Array", "Int8Array", "Int16Array", "Int32Array", "Uint8Array",
    "Uint16Array", "Uint32Array", "Uint8ClampedArray", "BigInt64Array",
    "BigUint64Array", "BigInt", "globalThis", "fetch", "Request", "Response",
    "Headers", "URL", "URLSearchParams", "FormData", "Blob", "File", "FileReader",
    # 浏览器特有全局
    "window", "document", "navigator", "location", "history", "localStorage",
    "sessionStorage", "alert", "confirm", "prompt", "screen", "frames",
    # reserved words
    "if", "else", "for", "while", "do", "switch", "case", "default", "break",
    "continue", "return", "throw", "try", "catch", "finally", "function",
    "class", "extends", "super", "this", "new", "delete", "typeof", "instanceof",
    "in", "of", "var", "let", "const", "async", "await", "yield", "static",
    "get", "set", "void", "null", "true", "false", "import", "export", "from",
    "as", "default",
})


# ---------------------------------------------------------------------------
# Node.js globals（`nodejs` lang 字段用）
# ---------------------------------------------------------------------------

_NODE_GLOBALS_KW = frozenset({
    # Node.js globals
    "console", "log", "process", "Buffer", "module", "exports", "require", "__dirname",
    "__filename", "global", "globalThis", "undefined", "NaN", "Infinity",
    "isNaN", "isFinite", "parseInt", "parseFloat", "encodeURI", "decodeURI",
    "encodeURIComponent", "decodeURIComponent", "setTimeout", "setInterval",
    "clearTimeout", "clearInterval", "setImmediate", "clearImmediate",
    "queueMicrotask", "performance", "fetch", "Promise", "Symbol", "Proxy",
    "Reflect", "JSON", "Math", "Date", "Object", "Array", "Function", "Boolean",
    "Number", "String", "RegExp", "Error", "TypeError", "RangeError",
    "SyntaxError", "Map", "Set", "WeakMap", "WeakSet", "URL", "URLSearchParams",
    "TextEncoder", "TextDecoder", "BigInt",
    # Node 核心模块（require 进来当 namespace 用的常量名）
    "fs", "path", "http", "https", "stream", "events", "util", "os", "crypto",
    "zlib", "child_process", "cluster", "dgram", "dns", "net", "tls", "readline",
    "repl", "tty", "vm", "worker_threads", "assert", "querystring",
    # reserved words
    "if", "else", "for", "while", "do", "switch", "case", "default", "break",
    "continue", "return", "throw", "try", "catch", "finally", "function",
    "class", "extends", "super", "this", "new", "delete", "typeof", "instanceof",
    "in", "of", "var", "let", "const", "async", "await", "yield", "static",
    "get", "set", "void", "null", "true", "false", "import", "export", "from",
    "as", "default",
})


# 通用正则（多语言共用）：过滤 dunder / 双下划线
_DUNDER_RE = re.compile(r"^__.*__$")


# ---------------------------------------------------------------------------
# 抽取函数：按语言分派
# ---------------------------------------------------------------------------


def _extract_python_imports(code_text: str) -> Set[str]:
    """提取 Python 顶级 import / from 的模块名集合（去重）。

    支持：
    - `import X` / `import X as Y` / `import X.Y`
    - `from X import Y` / `from X.Y import Z`
    收集的是顶层模块名（`import X.Y.Z` → `X`）。
    """
    imports: Set[str] = set()
    for m in re.finditer(r"^\s*import\s+([\w.]+)(?:\s+as\s+\w+)?", code_text, re.MULTILINE):
        imports.add(m.group(1).split(".")[0])
    for m in re.finditer(r"^\s*from\s+([\w.]+)\s+import", code_text, re.MULTILINE):
        imports.add(m.group(1).split(".")[0])
    return imports


def _extract_js_imports(code_text: str) -> Set[str]:
    """提取 JavaScript / Node.js 的模块名集合（去重）。

    支持：
    - ES module `import X from 'mod'` / `import { a, b } from 'mod'` / `import * as X from 'mod'`
    - CommonJS `const X = require('mod')` / `let X = require('mod')`
    - 单独 `require('mod')` 调用
    收集的是裸模块名字符串。
    """
    imports: Set[str] = set()
    for m in re.finditer(r"""\bfrom\s+['"]([^'"]+)['"]""", code_text):
        imports.add(m.group(1))
    for m in re.finditer(r"""\brequire\(\s*['"]([^'"]+)['"]\s*\)""", code_text):
        imports.add(m.group(1))
    return imports


def _extract_function_calls(code_text: str, ignore_set: frozenset) -> Set[str]:
    """提取 name(...) 形式的调用名集合（过滤掉 ignore_set + dunder）。

    Args:
        code_text: 源代码
        ignore_set: 该语言的 builtins/keywords frozenset
    """
    calls: Set[str] = set()
    for m in re.finditer(r"\b(\w+)\s*\(", code_text):
        name = m.group(1)
        if name in ignore_set:
            continue
        if _DUNDER_RE.match(name):
            continue
        calls.add(name)
    return calls


# ---------------------------------------------------------------------------
# 顶层入口
# ---------------------------------------------------------------------------

# 语言归一化：用户传 "py" / "js" / "node" 等别名时 → 标准 lang
_LANG_ALIASES = {
    "py": "python",
    "python": "python",
    "js": "javascript",
    "javascript": "javascript",
    "node": "nodejs",
    "nodejs": "nodejs",
}

# 支持的语言（归一化后）
SUPPORTED_LANGUAGES = frozenset({"python", "nodejs", "javascript"})


def code_fingerprint(args: dict) -> str:
    """code 工具的语义指纹，用于永久批准的精确匹配。

    Args:
        args: code 工具的 args dict（含 `code` / `source` / `language` / `use_sandbox`）

    Returns:
        "code_fp:lang=X|sandbox=Y|imp=a,b|fn=c,d" 形式的稳定字符串。
        空字符串 → 不可 fingerprint（空 code 或不支持的语言），不写持久化。
    """
    code_text = (args.get("code") or args.get("source") or "").strip()
    if not code_text:
        return ""
    lang_raw = (args.get("language") or "python").lower()
    lang = _LANG_ALIASES.get(lang_raw, lang_raw)
    if lang not in SUPPORTED_LANGUAGES:
        return ""
    use_sandbox = bool(args.get("use_sandbox", True))

    if lang == "python":
        imports = _extract_python_imports(code_text)
        calls = _extract_function_calls(code_text, _PY_BUILTINS_KW)
    elif lang == "javascript":
        imports = _extract_js_imports(code_text)
        calls = _extract_function_calls(code_text, _JS_GLOBALS_KW)
    elif lang == "nodejs":
        imports = _extract_js_imports(code_text)
        calls = _extract_function_calls(code_text, _NODE_GLOBALS_KW)
    else:  # pragma: no cover（SUPPORTED_LANGUAGES 过滤）
        return ""

    parts = [f"lang={lang}", f"sandbox={int(use_sandbox)}"]
    if imports:
        parts.append("imp=" + ",".join(sorted(imports)))
    if calls:
        parts.append("fn=" + ",".join(sorted(calls)))
    return CODE_FP_PREFIX + "|".join(parts)
