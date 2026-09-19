"""背备不悲 · 日志配置"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"

_CONSOLE_FMT = "%(asctime)s | %(levelname)-7s | %(name)-28s | %(message)s"
_DATE_FMT = "%H:%M:%S"


def setup_logging(level: str = "INFO") -> None:
    log_level = getattr(logging, level.upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(log_level)

    # 清掉 uvicorn 可能已装的 handler，避免日志重复
    for handler in list(root.handlers):
        root.removeHandler(handler)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter(_CONSOLE_FMT, datefmt=_DATE_FMT))
    root.addHandler(console)

    # 文件日志，方便排查长任务
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(LOG_DIR / "agent.log", encoding="utf-8")
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)-28s | %(message)s")
        )
        root.addHandler(file_handler)
    except OSError:
        pass  # 磁盘/权限问题不应导致启动失败

    # 第三方库降噪
    for noisy in ("httpx", "httpcore", "urllib3", "pymilvus", "milvus_lite"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
