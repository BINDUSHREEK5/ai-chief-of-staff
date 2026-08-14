"""One place to configure logging so every module's `getLogger("agent.*")`
calls come out consistently formatted, in files and in `docker logs`."""
from __future__ import annotations

import logging
import sys


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger("agent")
    root.setLevel(level.upper())

    if root.handlers:
        return  # already configured (e.g. re-imported during tests)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
    )
    root.addHandler(handler)

    # Quiet down noisy third-party loggers unless we're debugging.
    if level.upper() != "DEBUG":
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)