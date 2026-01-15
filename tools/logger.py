import logging
import json
import uuid
import sys
import os
from datetime import datetime
from contextvars import ContextVar
from typing import Optional

# Context Variables to hold request-scoped data
request_id_ctx = ContextVar("request_id", default=None)
trace_id_ctx = ContextVar("trace_id", default=None)
user_id_ctx = ContextVar("user_id", default=None)
session_id_ctx = ContextVar("session_id", default=None)

class CustomJSONFormatter(logging.Formatter):
    """
    Formatter to output logs in JSON format matching the mandatory policy.
    """
    def format(self, record):
        log_record = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "service": "lexi-ai",  # You might want to make this configurable
            "layer": "backend",
            "module": record.module,
            "function": record.funcName,
            "log_level": record.levelname,
            "message": record.getMessage(),
            # "status_code": getattr(record, "status_code", None), # Can be passed via extra={}
            "request_id": request_id_ctx.get(),
            "trace_id": trace_id_ctx.get(),
            "user_id": user_id_ctx.get(),
            "session_id": session_id_ctx.get()
        }

        # Merge extra fields if they exist (e.g. status_code passed in extra)
        if hasattr(record, "status_code"):
            log_record["status_code"] = record.status_code
        
        # Include exception info if present
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)
            log_record["stack_trace"] = self.formatStack(record.stack_info) if record.stack_info else None

        return json.dumps(log_record)

def get_logger(name: str) -> logging.Logger:
    """
    Returns a configured logger with JSON formatter.
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False # Prevent double logging if root logger is touched elsewhere

    # Check if handler already exists to avoid duplicate logs
    if not logger.handlers:
        formatter = CustomJSONFormatter()

        # Stream Handler (Console)
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

        # File Handler (logs/app.log)
        log_dir = "logs"
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
        
        file_handler = logging.FileHandler(os.path.join(log_dir, "app.log"))
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger

# Configure root logger as well to catch external library logs if needed, 
# or just ensure our app logger is used.
# For this specific task, we'll rely on get_logger usage.
