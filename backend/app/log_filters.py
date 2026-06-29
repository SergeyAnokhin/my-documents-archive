import logging


class SuppressNoisyPaths(logging.Filter):
    """Drop high-frequency polling noise from access logs."""
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return "GET /api/tasks" not in msg and "GET /api/health" not in msg
