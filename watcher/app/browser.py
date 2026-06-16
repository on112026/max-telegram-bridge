"""Инициализация браузера Playwright (persistent context).

Поддерживает два режима:
  - headless: chromium без дисплея (по умолчанию, для прода)
  - headful:  chromium подключается к X-серверу (DISPLAY=:99),
              используется для ручного управления через Telegram/noVNC.
"""

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
        # Режим headful задан либо через env, либо будет включён
        # командой set_headful() (например, из /reauth в Telegram).
        env_headful = os.getenv("WATCHER_HEADFUL_DEFAULT", "0") == "1"
        env_display = os.getenv("DISPLAY", "")
        self._headful = env_headful or bool(env_display)

    @property
    def headful(self) -> bool:
        return self._headful

    async def start(self) -> None:
        os.makedirs(settings.profile_dir, exist_ok=True)
        self._pw = await async_playwright().start()
        launch_kwargs = dict(
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
        # Если headful и есть $DISPLAY — пробросим в Chromium явно.
        display = os.getenv("DISPLAY")
        if self._headful and display:
            launch_kwargs["env"] = {**os.environ, "DISPLAY": display}
        self.context = await self._pw.chromium.launch_persistent_context(**launch_kwargs)
        if self.context.pages:
            self.page = self.context.pages[0]
        else:
            self.page = await self.context.new_page()
        logger.info(
            "Browser started (headless=%s, display=%s) profile=%s",
            not self._headful,
            display or "<none>",
            settings.profile_dir,
        )

    async def goto_max(self) -> None:
        assert self.page is not None
        await self.page.goto(settings.max_web_url, wait_until="domcontentloaded", timeout=60000)
        try:
            await self.page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:  # pragma: no cover
            pass

    async def set_headful(self, headful: bool) -> None:
        """Переключает режим headless<->headful. Перезапускает контекст.

        Используется при ручном управлении через Telegram: watcher
        останавливает listener, переключает Chromium в headful с DISPLAY=:99,
        чтобы пользователь мог видеть/управлять страницей (через noVNC или
        через inline-кнопки).
        """

        if headful == self._headful and self.context is not None:
            return
        logger.info("Switching browser headful=%s (was %s)", headful, self._headful)
        # Закрываем старый контекст
        try:
            if self.context:
                await self.context.close()
        except Exception:
            pass
        self.context = None
        self.page = None
        self._headful = headful
        await self.start()

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