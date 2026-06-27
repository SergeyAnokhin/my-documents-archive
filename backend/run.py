"""Entry point: python run.py"""
import uvicorn
from pathlib import Path

Path("logs").mkdir(exist_ok=True)

_LOG_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "()": "uvicorn.logging.DefaultFormatter",
            "fmt": "%(asctime)s.%(msecs)03d %(levelprefix)s %(message)s",
            "datefmt": "%H:%M:%S",
            "use_colors": None,
        },
        "access": {
            "()": "uvicorn.logging.AccessFormatter",
            "fmt": '%(asctime)s.%(msecs)03d %(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s',
            "datefmt": "%H:%M:%S",
        },
        "file": {
            "format": "%(asctime)s.%(msecs)03d  %(levelname)-7s  %(name)s  %(message)s",
            "datefmt": "%H:%M:%S",
        },
    },
    "handlers": {
        "default": {
            "formatter": "default",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stderr",
        },
        "access": {
            "formatter": "access",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
        },
        "file": {
            "formatter": "file",
            "class": "logging.handlers.RotatingFileHandler",
            "filename": "logs/backend.log",
            "maxBytes": 2097152,   # 2 MB, then rotate
            "backupCount": 1,
            "encoding": "utf-8",
        },
    },
    "loggers": {
        "uvicorn":        {"handlers": ["default", "file"], "level": "INFO",  "propagate": False},
        "uvicorn.error":  {"handlers": ["default", "file"], "level": "INFO",  "propagate": False},
        "uvicorn.access": {"handlers": ["access",  "file"], "level": "INFO",  "propagate": False},
        # DEBUG so search step logs (log.debug) are visible while investigating
        "app":            {"handlers": ["default", "file"], "level": "DEBUG", "propagate": False},
    },
}

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True, log_config=_LOG_CONFIG)
