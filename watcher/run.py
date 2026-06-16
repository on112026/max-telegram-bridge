"""Entrypoint для контейнера watcher.

Стартует:
  1. Headful-control HTTP-сервер (aiohttp, порт 9000) — для команд от api
  2. Главный цикл watcher'а (loop.main) — логин, listener, send-queue
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared"))
sys.path.insert(0, str(ROOT / "watcher"))

from shared.config import load_settings
from shared.log_setup import configure_logging


def main() -> None:
    settings = load_settings()
    configure_logging(settings.log_level)
    logging.getLogger(__name__).info("Starting watcher entrypoint")
    from app.headful_api import run_headful_server
    from app.loop import main as run_loop

    async def _both() -> None:
        await asyncio.gather(
            run_headful_server(host="127.0.0.1", port=9000),
            run_loop(),
        )

    try:
        asyncio.run(_both())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()