from __future__ import annotations
import logging
from pathlib import Path
from datetime import datetime

# --------------------------------------------------
# Paths
# --------------------------------------------------
BASE_DIR = Path(__file__).resolve().parents[2]
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

# --------------------------------------------------
# Helpers
# --------------------------------------------------
def today():
    return datetime.now().strftime("%Y-%m-%d")


LOG_FORMAT = (
    "%(asctime)s | %(levelname)s | %(name)s | "
    "%(filename)s:%(lineno)d | %(message)s"
)


def setup_logging():
    formatter = logging.Formatter(LOG_FORMAT)

    # ---------------------------
    # Application log
    # ---------------------------
    app_log_file = LOG_DIR / f"application_{today()}.log"
    app_handler = logging.FileHandler(app_log_file, encoding="utf-8")
    app_handler.setLevel(logging.INFO)
    app_handler.setFormatter(formatter)

    # ---------------------------
    # Error log
    # ---------------------------
    error_log_file = LOG_DIR / f"error_{today()}.log"
    error_handler = logging.FileHandler(error_log_file, encoding="utf-8")
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)

    # ---------------------------
    # Console log
    # ---------------------------
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()   #  Important to avoid duplicates
    root.addHandler(app_handler)
    root.addHandler(error_handler)
    root.addHandler(console_handler)

    # Disable SQLAlchemy logs
    logging.getLogger("sqlalchemy").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.orm").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)


def get_logger(name: str):
    return logging.getLogger(name)
