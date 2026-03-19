"""
Shared structured logging setup for all CSL scripts.

Provides a single ``get_logger(name)`` entry-point that every module can
import.  The first call configures the root logger once; subsequent calls
just return a child logger.

Usage::

    from csl_logging import get_logger
    log = get_logger("csl_bot")
    log.info("Processing tab", extra={"tab": "DHL", "row_count": 42})

Environment variables
---------------------
LOG_FORMAT : str
    ``"json"`` (default) for machine-parseable JSON lines, or ``"text"``
    for human-readable console output.
LOG_LEVEL : str
    Standard Python level name (default ``"INFO"``).
"""

import logging
import os
import sys

_CONFIGURED = False


def _setup_root(level_name: str, fmt: str) -> None:
    """Configure the root logger exactly once."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    _CONFIGURED = True

    level = getattr(logging, level_name.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)

    # Remove any existing handlers (e.g. from prior basicConfig calls)
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)

    if fmt == "json":
        try:
            from pythonjsonlogger import jsonlogger

            formatter = jsonlogger.JsonFormatter(
                fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
                rename_fields={"asctime": "timestamp", "levelname": "level",
                               "name": "logger"},
                datefmt="%Y-%m-%dT%H:%M:%S",
            )
        except ImportError:
            # Graceful fallback if python-json-logger is not installed
            formatter = logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
    else:
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    handler.setFormatter(formatter)
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger, configuring the root logger on first call.

    Safe to call from any module at import time — the root logger is set up
    once using ``LOG_FORMAT`` and ``LOG_LEVEL`` environment variables.
    """
    _setup_root(
        level_name=os.environ.get("LOG_LEVEL", "INFO"),
        fmt=os.environ.get("LOG_FORMAT", "json"),
    )
    return logging.getLogger(name)
