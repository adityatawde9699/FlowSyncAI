"""Small JSON structured logging setup for API and worker processes."""
import json
import logging
import os
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({"timestamp": datetime.now(timezone.utc).isoformat(), "level": record.levelname,
            "logger": record.name, "message": record.getMessage(),
            **({"exception": self.formatException(record.exc_info)} if record.exc_info else {})}, ensure_ascii=False)


def configure_logging():
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(os.environ.get("FLOWSYNC_LOG_LEVEL", "INFO").upper())
