"""Entrypoint для контейнера watcher."""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared"))
sys.path.insert(0, str(ROOT / "watcher"))

from shared.config import load_settings
from shared.logging import configure_logging


def main() -> None:
    settings = load_settings()
    configure_logging(settings.log_level)
    logging.getLogger(__name__).info("Starting watcher entrypoint")
    from app.loop import main as run_loop

    asyncio.run(run_loop())


if __name__ == "__main__":
    main()