"""Shared DataAnalysis database configuration for sandbox code.

The runtime directory is mounted writable by CodeSandboxPool and is shared by
all sandbox containers. Secrets are stored locally and are never returned by
listing helpers.
"""
from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


_RUNTIME_DIR = Path(__file__).resolve().parent / ".runtime"
_CONFIG_PATH = _RUNTIME_DIR / "databases.json"
_LOCK_PATH = _RUNTIME_DIR / ".databases.lock"


def _runtime_dir() -> Path:
    _RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    return _RUNTIME_DIR


@contextmanager
def _locked() -> Iterator[None]:
    _runtime_dir()
    with _LOCK_PATH.open("a+") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _read() -> dict[str, dict[str, Any]]:
    if not _CONFIG_PATH.exists():
        return {}
    with _CONFIG_PATH.open("r", encoding="utf-8") as f:
        value = json.load(f)
    return value if isinstance(value, dict) else {}


def _write(value: dict[str, dict[str, Any]]) -> None:
    runtime_dir = _runtime_dir()
    fd, temp_name = tempfile.mkstemp(prefix="databases.", suffix=".tmp", dir=runtime_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_name, _CONFIG_PATH)
        try:
            os.chmod(_CONFIG_PATH, 0o600)
        except OSError:
            pass
    finally:
        Path(temp_name).unlink(missing_ok=True)


def save_database_config(alias: str, engine: str, **connection: Any) -> dict[str, Any]:
    """Save or replace one shared database connection configuration."""
    alias = alias.strip()
    engine = engine.strip().lower()
    if not alias or not alias.replace("_", "").replace("-", "").isalnum():
        raise ValueError("alias 只能包含字母、数字、下划线和短横线")
    if engine not in {"mysql", "sqlite", "postgres", "postgresql", "mongo", "mongodb"}:
        raise ValueError("engine 必须是 mysql、sqlite、postgresql 或 mongodb")

    config = {"engine": engine, **connection}
    with _locked():
        configs = _read()
        configs[alias] = config
        _write(configs)
    return _public(alias, config)


def list_database_configs() -> list[dict[str, Any]]:
    with _locked():
        configs = _read()
    return [_public(alias, config) for alias, config in configs.items()]


def load_database_config(alias: str) -> dict[str, Any]:
    with _locked():
        configs = _read()
    try:
        return dict(configs[alias])
    except KeyError as exc:
        raise KeyError(f"未找到数据库配置: {alias}") from exc


def delete_database_config(alias: str) -> None:
    with _locked():
        configs = _read()
        configs.pop(alias, None)
        _write(configs)


def _public(alias: str, config: dict[str, Any]) -> dict[str, Any]:
    return {
        "alias": alias,
        "engine": config.get("engine"),
        "host": config.get("host"),
        "port": config.get("port"),
        "database": config.get("database"),
        "description": config.get("description", ""),
    }


@contextmanager
def database_config(alias: str) -> Iterator[dict[str, Any]]:
    yield load_database_config(alias)


__all__ = [
    "database_config",
    "delete_database_config",
    "list_database_configs",
    "load_database_config",
    "save_database_config",
]
