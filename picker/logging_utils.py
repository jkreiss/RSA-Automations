import json
import logging
from datetime import datetime

from picker.config import LOG_DIR


LOG_FORMATTER = logging.Formatter(
    "%(asctime)s %(levelname)s %(name)s %(message)s",
    "%Y-%m-%d %H:%M:%S",
)
LOGGER_CACHE = {}


def generate_job_id():
    return "MYS" + datetime.now().strftime("%m%d%H%M")


def get_log_file(job_id):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return LOG_DIR / f"{job_id}.log"


def get_logger(job_id):
    if job_id not in LOGGER_CACHE:
        logger = logging.getLogger(f"picker_automation.{job_id}")
        logger.setLevel(logging.INFO)
        logger.handlers.clear()

        file_handler = logging.FileHandler(get_log_file(job_id))
        file_handler.setFormatter(LOG_FORMATTER)
        logger.addHandler(file_handler)
        logger.propagate = False
        LOGGER_CACHE[job_id] = logger

    return LOGGER_CACHE[job_id]


def log_event(event, level="info", **context):
    payload = {"event": event, **context}
    job_id = context.get("job_id") or "unknown_job"
    getattr(get_logger(job_id), level)(json.dumps(payload, default=str, sort_keys=True))

