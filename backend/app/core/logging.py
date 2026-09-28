"""Structured JSON logging with request IDs and secret redaction."""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone

from app.core.context import _request_id

_SECRET_RE = re.compile(
    r"(hsk_[A-Za-z0-9_]+|gsk_[A-Za-z0-9]+|sk-[A-Za-z0-9]{12,}|Bearer\s+[A-Za-z0-9._\-]+)"
)


def redact(text: str) -> str:
    return _SECRET_RE.sub("[REDACTED]", text)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(record.getMessage()),
        }
        request_id = _request_id.get()
        if request_id:
            payload["request_id"] = request_id
        for key in ("event", "latency_ms", "status", "path", "method", "project_id", "op"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, default=str)


_configured = False


def configure_logging(level: str = "INFO") -> None:
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger("projectpulse")
    root.handlers = [handler]
    root.setLevel(level.upper())
    root.propagate = False
    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"projectpulse.{name}")
