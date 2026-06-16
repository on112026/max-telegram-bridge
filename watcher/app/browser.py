"""Инициализация браузера Playwright (persistent context)."""

from __future__ import annotations

import logging
import os
from typing import Optional

from playwright.async_api import BrowserContext, Page, Playwright, async_playwright

from app.config import settings

logger = logging.getLogger(__name__)


class BrowserSession:
    def __init__(self) -> None:
        self._pw: Optional[Playwright] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self._headful = os.getenv("HEADFUL", "0") == "1"

    async def start(self) -> None:
        os.makedirs(settings.profile_dir, exist_ok=True)
        self._pw = await async_playwright().start()
        self.context = await self._pw.chromium.launch_persistent_context(
            user_data_dir=settings.profile_dir,
            headless=not self._headful,
            executable_path=os.getenv("CHROMIUM_PATH", "/usr/bin/chromium"),
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--no-first-run",
            ],
        )
        # Используем первую страницу или создаём новую
        if self.context.pages:
            self.page = self.context.pages[0]
        else:
            self.page = await self.context.new_page()
        logger.info(
            "Browser started (headless=%s) profile=%s",
            not self._headful,
            settings.profile_dir,
        )

    async def goto_max(self) -> None:
        assert self.page is not None
        await self.page.goto(settings.max_web_url, wait_until="domcontentloaded", timeout=60000)
        # Даём SPA чуть-чуть прогрузиться
        try:
            await self.page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:  # pragma: no cover
            pass

    async def close(self) -> None:
        try:
            if self.context:
                await self.context.close()
        except Exception:
            pass
        try:
            if self._pw:
                await self._pw.stop()
        except Exception:
            pass
        logger.info("Browser closed")

    async def alive(self) -> bool:
        if not self.context or not self.page:
            return False
        try:
            await self.page.title()
            return True
        except Exception:
            return False