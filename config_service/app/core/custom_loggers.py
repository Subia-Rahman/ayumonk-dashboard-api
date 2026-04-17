import logging
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parents[2]
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


def get_file_logger(name: str, prefix: str) -> logging.Logger:
    today = datetime.now().strftime("%Y-%m-%d")
    log_file = LOG_DIR / f"{prefix}_{today}.log"

    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    if logger.handlers:
        return logger

    handler = logging.FileHandler(log_file, encoding="utf-8")
    handler.setFormatter(logging.Formatter(LOG_FORMAT))

    logger.addHandler(handler)
    logger.propagate = False  # VERY IMPORTANT

    return logger
