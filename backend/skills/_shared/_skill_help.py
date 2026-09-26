"""AI 按需查询 skill 函数 / 类方法 docstring 的统一入口。

## 为什么用原生 inspect 而不用装饰器

- 装饰器（`@register_doc`）要在每个函数 / 方法上加，类方法 / property / staticmethod 要分开处理
- 已经写好的函数（100+ 行）都要改一遍才能用装饰器
- `inspect.getmembers + signature + getdoc` 自动覆盖所有类型（function / classmethod / staticmethod / property / class）
- **零样板代码**——每个 skill 末尾只加 5 行 `help()` 模板即可

## 调用方式

每个 skill 模块（如 `skills.WordEditor`）末尾暴露 `help(name=None)` 和 `doc(name=None)`：

    from skills.WordEditor import help
    print(help())                   # 列出全部函数 / 类签名 + summary
    print(help("WordDoc"))          # 单个类详细 docstring + 方法列表
    print(help("WordDoc.create"))   # 单个方法详细 docstring

## Why

SKILL.md 受 token 限制只能放最常用 80% 用法 + 极简示例；AI 真正要写代码时会撞到边角参数 / Returns / Raises / 异常类型等细节。`help(name)` 让 AI 按需一次性拿到完整 docstring，避免 SKILL.md 膨胀到 200+ 行。

## How to apply

新增 skill 时，在 `__init__.py` 末尾加：

    def doc(name=None):
        import sys
        from _shared._skill_help import skill_help
        return skill_help(sys.modules[__name__], name)

    def help(name=None):
        return doc(name)
"""
import inspect
from typing import Any


def _resolve(module: Any, path: str) -> Any | None:
    """`module.attr1.attr2` 链式解析；返回对象或 None。"""
    obj = module
    for part in path.split("."):
        obj = getattr(obj, part, None)
        if obj is None:
            return None
    return obj


def _signature(obj: Any) -> str:
    """返回方法签名（如 `(self, path=None)`）。失败回退 `()`。"""
    try:
        return str(inspect.signature(obj))
    except (ValueError, TypeError):
        return "()"


def _summary(obj: Any) -> str:
    """取 docstring 第一行（summary line）。"""
    docstr = inspect.getdoc(obj) or ""
    return docstr.split("\n", 1)[0].strip() if docstr else "(无 docstring)"


def _is_skill_local(obj: Any, module: Any) -> bool:
    """判断 obj 是不是真正定义在 module 里（防止 import 进来的 stdlib / 其他模块成员被误列）。"""
    return getattr(obj, "__module__", None) == module.__name__


def skill_help(module: Any, name: str | None = None) -> str:
    """列出 skill 模块全部函数 / 类，或返回单个目标的完整 docstring。

    Args:
        module: skill 模块对象（通常是 `sys.modules[__name__]`）
        name: None 列出全部；str 返回该函数 / 类 / 方法的完整 docstring
            （链式如 `"WordDoc.create"`）

    Returns:
        字符串（直接 print 即可看）

    Examples:
        >>> from skills.WordEditor import help
        >>> print(help())
        === skills.WordEditor 全部导出 ===
          WordDoc.create(path=None) -> "WordDoc"  # 创建空白 docx
          WordDoc.open(path) -> "WordDoc"  # 打开已有 docx
        ...
          class WordDoc  # Word 文档封装
            WordDoc.add_paragraph(text, *, ...) -> "_WordParagraph"  # 加段落
            ...

        >>> print(help("WordDoc.create"))
        WordDoc.create(path=None)

        创建空白 docx。

        Returns:
            WordDoc 实例
    """
    if name is None:
        lines = [f"=== {module.__name__} 全部导出 ==="]

        # 顶层函数
        for n, m in sorted(inspect.getmembers(module, predicate=inspect.isfunction)):
            if n.startswith("_") or n in ("skill_help", "doc", "help"):
                continue
            if not _is_skill_local(m, module):
                continue
            lines.append(f"  {n}{_signature(m)}  # {_summary(m)}")

        # 类（列类签名 + 类 docstring 摘要 + 方法列表）
        for cn, c in sorted(inspect.getmembers(module, predicate=inspect.isclass)):
            if cn.startswith("_"):
                continue
            if not _is_skill_local(c, module):
                continue
            lines.append(f"\n  class {cn}{_signature(c)}  # {_summary(c)}")
            for mn, ma in sorted(inspect.getmembers(c, predicate=inspect.isfunction)):
                if mn.startswith("_") or mn in ("doc", "help"):
                    continue
                lines.append(f"    {cn}.{mn}{_signature(ma)}  # {_summary(ma)}")
            # property（非 function 但常暴露给 AI）
            for pn, p in sorted(inspect.getmembers(c, predicate=inspect.isdatadescriptor)):
                if pn.startswith("_"):
                    continue
                if isinstance(p, property):
                    lines.append(f"    {cn}.{pn}  # property: {_summary(p.fget or property())}")

        return "\n".join(lines) or f"({module.__name__} 无导出)"

    # 单个查询
    obj = _resolve(module, name)
    if obj is None:
        available = sorted([
            n for n, _ in inspect.getmembers(module)
            if not n.startswith("_") and not n.startswith("__")
        ])[:20]
        return f"[未找到] {name!r}\n可用的前 20 个: {', '.join(available)}"

    header = f"{name}{_signature(obj)}"
    docstr = inspect.getdoc(obj) or "[无 docstring]"
    return f"{header}\n\n{docstr}"


class _HelpMeta(type):
    """metaclass: 自动给类的所有 callable 挂 .help 属性 + 类自身挂自身 docstring。

    使用 `class WordDoc(metaclass=_HelpMeta):` 后：
    - `WordDoc.add_paragraph.help` 直接拿方法 docstring
    - `WordDoc.help` 拿类自身 docstring（不再需要 `help("WordDoc")`）

    Why: AI 拿到一个类或方法都能一行调 `.help` 看怎么用，不用先 import help() 函数。
    """
    def __new__(mcs, name, bases, ns):
        cls = super().__new__(mcs, name, bases, ns)
        # 类自身挂 .help（类 docstring summary）—— 让 `ExcelDoc.help` 也一行拿
        cls.help = inspect.getdoc(cls) or "(无类 docstring)"
        for attr_name, attr in list(vars(cls).items()):
            if attr_name.startswith("_"):
                continue
            if isinstance(attr, (staticmethod, classmethod)):
                func = attr.__func__
                func.help = inspect.getdoc(func) or "(无 docstring)"
                setattr(cls, attr_name, type(attr)(func))
            elif isinstance(attr, property):
                if attr.fget:
                    attr.fget.help = inspect.getdoc(attr.fget) or "(无 docstring)"
            elif callable(attr):
                attr.help = inspect.getdoc(attr) or "(无 docstring)"
        return cls


def auto_attach_help_module(module):
    """给模块顶层所有 callable 自动挂 .help 属性。

    使用：在 skill `__init__.py` 末尾调 `auto_attach_help_module(sys.modules[__name__])`
    后，`from skills.X import func; func.help` 直接拿 docstring。
    """
    for name, obj in list(vars(module).items()):
        if name.startswith("_"):
            continue
        if name in ("doc", "help", "auto_attach_help_module", "_HelpMeta"):
            continue
        # 跳过 typing 类型（Any / List / Optional 等 immutable）
        mod = getattr(obj, "__module__", None)
        if mod and (mod.startswith("typing") or mod.startswith("_collections_abc")):
            continue
        if callable(obj) and not isinstance(obj, type):
            try:
                obj.help = inspect.getdoc(obj) or "(无 docstring)"
            except (AttributeError, TypeError):
                pass  # immutable types（如 typing.List）跳过