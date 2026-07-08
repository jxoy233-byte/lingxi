"""
自动加载：Python 启动时 import site 时会找 sitecustomize。
挂在 /usr/local/lib/python3.12/site-packages/ 下，patch os/scandir/pathlib
让 /skills /cached 根目录下的系统垃圾（.DS_Store、__pycache__/、__init__.py）
子目录不再过滤；
"""
import os
import builtins
from pathlib import Path

# 只在这两个挂载点下过滤，其他路径保持原样
_FILTERED_ROOTS = ("/skills", "/cached")


def _is_under_filtered_root(path):
    """只在 /skills 和 /cached 这两个根目录层过滤，子目录不再过滤

    只挡住一眼可见的系统垃圾（.DS_Store、__pycache__/、__init__.py），
    深入子目录后让用户/模型看到所有文件，避免误伤。
    """
    if not isinstance(path, (str, bytes, os.PathLike)):
        return False
    p = os.fspath(path)
    return p == "/skills" or p == "/cached"


# --- patch os.listdir ---
_original_listdir = os.listdir

def _is_hidden(name):
    """过滤以 . 或 __ 开头的隐藏/系统垃圾文件

    - 以 . 开头 → .DS_Store（macOS Finder 垃圾）等
    - 以 __ 开头 → __pycache__/（Python 缓存目录）、__init__.py（包标记）等
    - 以单 _ 开头 → 不过滤（_meta.json 是 ChatDataAnalysis 的生成计数器，模型要能看到）
    """
    return isinstance(name, str) and (name.startswith(".") or name.startswith("__"))


def _patched_listdir(path="."):
    entries = _original_listdir(path)
    if _is_under_filtered_root(path):
        entries = [e for e in entries if not _is_hidden(e)]
    return entries

os.listdir = _patched_listdir


# --- patch os.scandir ---
_original_scandir = os.scandir

class _FilteredScandir:
    """包装 scandir 返回的 iterator，过滤掉 . 或 __ 开头的隐藏/系统垃圾文件

    同时实现 __iter__ 和 __next__：
    - __iter__：让 for entry in obj 工作
    - __next__：让 next(obj) 工作（os.walk 内部用 next() 遍历 scandir）
    """
    def __init__(self, raw_iter, should_filter):
        # 存原始 iterator，每次 __iter__ 时包一层过滤生成新的 generator
        self._raw = raw_iter
        self._filter = should_filter
        self._gen = None  # 懒生成，第一次 __iter__ 时创建

    def _make_gen(self):
        for entry in self._raw:
            if self._filter and _is_hidden(entry.name):
                continue
            yield entry

    def __iter__(self):
        # 每次 __iter__ 都返回新的 generator，支持多次遍历
        self._gen = self._make_gen()
        return self._gen

    def __next__(self):
        # os.walk 用 next() 推进，必须实现
        if self._gen is None:
            self._gen = self._make_gen()
        return next(self._gen)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        # 关闭原始 scandir iterator
        close = getattr(self._raw, "close", None)
        if close:
            close()
        return False


def _patched_scandir(path="."):
    it = _original_scandir(path)
    return _FilteredScandir(it, _is_under_filtered_root(path))

os.scandir = _patched_scandir


# --- patch pathlib.Path.iterdir ---
_original_path_iterdir = Path.iterdir

def _patched_path_iterdir(self):
    if _is_under_filtered_root(str(self)):
        return iter(e for e in _original_path_iterdir(self) if not _is_hidden(e.name))
    return _original_path_iterdir(self)

Path.iterdir = _patched_path_iterdir
