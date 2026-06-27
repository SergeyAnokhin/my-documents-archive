"""Entry point: python run.py"""
import uvicorn

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
    },
    "loggers": {
        "uvicorn":        {"handlers": ["default"], "level": "INFO", "propagate": False},
        "uvicorn.error":  {"handlers": ["default"], "level": "INFO", "propagate": False},
        "uvicorn.access": {"handlers": ["access"],  "level": "INFO", "propagate": False},
        "app":            {"handlers": ["default"], "level": "INFO", "propagate": False},
    },
}

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True, log_config=_LOG_CONFIG)
