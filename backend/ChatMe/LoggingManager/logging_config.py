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


def set_logger(
    name: str = "ChatMe",
    log_level: int = logging.DEBUG,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
    log_dir=Path.cwd() / ".chatme" / "logs"
):
    """
    配置日志处理器

    Args:
        name: 日志名称
        log_level: 日志级别，默认 INFO
        max_bytes: 单个日志文件最大大小（字节），默认 10MB
        backup_count: 保留的备份文件数量，默认 5 个
        log_dir: 输出路径

    Returns:
        配置好的 Logger 实例
    """
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    logger.setLevel(log_level)

    log_file = log_dir / f"{datetime.now().strftime('%Y-%m-%d')}.log"

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


def get_logger(name: str = None, path=None) -> logging.Logger:
    """获取指定名字的 logger"""
    if name is None:
        return set_logger()
    if path:
        return set_logger(name=name, log_dir=path)
    return set_logger(name=name)
