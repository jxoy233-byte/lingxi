import logging
import atexit
import queue
from pathlib import Path
from datetime import datetime
from logging.handlers import RotatingFileHandler, QueueHandler, QueueListener


_log_listeners: dict[str, QueueListener] = {}


def _stop_log_listeners() -> None:
    for listener in list(_log_listeners.values()):
        listener.stop()
    _log_listeners.clear()


atexit.register(_stop_log_listeners)


def _setup_file_logger(
    name: str,
    log_file: Path,
    log_level: int,
    max_bytes: int,
    backup_count: int,
) -> logging.Logger:
    """
    共用的 logger 装配逻辑：RotatingFileHandler + QueueHandler + QueueListener。
    被 set_logger / set_thinking_chain_logger 共用。
    """
    log_file.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(log_level)

    formatter = logging.Formatter(
        fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )

    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)

    log_queue = queue.Queue()
    queue_handler = QueueHandler(log_queue)
    queue_handler.setLevel(log_level)

    listener = QueueListener(log_queue, file_handler, respect_handler_level=True)
    listener.start()
    _log_listeners[name] = listener

    logger.addHandler(queue_handler)

    return logger


def set_logger(
    name: str = "ChatMe",
    log_level: int = logging.DEBUG,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
    log_dir=Path.cwd() / ".chatme" / "logs"
):
    """
    配置主日志处理器（写主日志文件 `YYYY-MM-DD.log`）

    Args:
        name: 日志名称
        log_level: 日志级别，默认 INFO
        max_bytes: 单个日志文件最大大小（字节），默认 10MB
        backup_count: 保留的备份文件数量，默认 5 个
        log_dir: 输出路径

    Returns:
        配置好的 Logger 实例
    """
    log_file = log_dir / f"{datetime.now().strftime('%Y-%m-%d')}.log"
    return _setup_file_logger(
        name=name,
        log_file=log_file,
        log_level=log_level,
        max_bytes=max_bytes,
        backup_count=backup_count,
    )


def set_thinking_chain_logger(
    name: str = "ChatMe.thinking_chain",
    log_level: int = logging.INFO,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
    log_dir=Path.cwd() / ".chatme" / "logs"
):
    """
    配置 AI 思维链专用日志处理器（写独立文件 `thinking_chain-YYYY-MM-DD.log`）。

    用途：单独承载 ChatWorkflow 各节点的 AI 思维链格式化日志
    （`imp_ipt` / `react_context` / `react_context_after_compact` /
     `agent_node_in/out` / `should_end_in/decision` / `final_node_in_context/out`），
    与主日志隔离，便于按文件维度回溯 LLM 决策链而不被业务日志噪声淹没。

    文件命名规则：`thinking_chain-YYYY-MM-DD.log`，按天切分 + RotatingFileHandler 兜底。

    Args:
        name: 日志名称（与主 logger 命名空间隔离，避免 handler 串台）
        log_level: 日志级别，默认 INFO
        max_bytes: 单个日志文件最大大小（字节），默认 10MB
        backup_count: 保留的备份文件数量，默认 5 个
        log_dir: 输出路径（与主日志同目录，便于运维）

    Returns:
        配置好的 Logger 实例
    """
    log_file = log_dir / f"thinking_chain-{datetime.now().strftime('%Y-%m-%d')}.log"
    return _setup_file_logger(
        name=name,
        log_file=log_file,
        log_level=log_level,
        max_bytes=max_bytes,
        backup_count=backup_count,
    )


def get_logger(name: str = None, path=None) -> logging.Logger:
    """获取指定名字的主 logger"""
    if name is None:
        return set_logger()
    if path:
        return set_logger(name=name, log_dir=path)
    return set_logger(name=name)


def get_thinking_chain_logger(name: str = "ChatMe.thinking_chain", path=None) -> logging.Logger:
    """获取 AI 思维链专用 logger（写独立文件 `thinking_chain-YYYY-MM-DD.log`）"""
    if path:
        return set_thinking_chain_logger(name=name, log_dir=path)
    return set_thinking_chain_logger(name=name)
