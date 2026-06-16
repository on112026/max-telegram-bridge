"""Контроллер headful-режима watcher'а.

Предоставляет набор команд, которые можно дёргать из API:
  - screenshot
  - click (x, y)
  - type (text)
  - key (key name)
  - fill (selector, value)
  - wait (selector, timeout)
  - evaluate (js)
  - url / back / forward / reload
  - scroll
  - cookies get/clear
  - set_headful / set_headless

Использует единственный инстанс BrowserSession, который создаётся
лениво (когда приходит первая команда) или держится общим с loop.py.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from app.browser import BrowserSession

logger = logging.getLogger(__name__)


# Список Playwright-клавиш, которые пропускаем как есть.
_VALID_KEYS = {
    "Enter", "Tab", "Escape", "Backspace", "Delete",
    "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight",
    "Home", "End", "PageUp", "PageDown", "F1", "F2", "F3", "F4", "F5",
    "F6", "F7", "F8", "F9", "F10", "F11", "F12",
    "Shift", "Control", "Alt", "Meta",
}


class HeadfulController:
    """Обёртка над BrowserSession с методами для API."""

    def __init__(self, session: Optional[BrowserSession] = None) -> None:
        self.session = session or BrowserSession()
        self._lock = asyncio.Lock()  # все операции сериализуются

    async def ensure_started(self) -> None:
        async with self._lock:
            if self.session.context is None:
                await self.session.start()

    async def set_headful(self, headful: bool) -> dict:
        async with self._lock:
            await self.session.set_headful(headful)
            return {"headful": self.session.headful, "url": self.session.page.url if self.session.page else None}

    async def goto_max(self) -> dict:
        await self.ensure_started()
        await self.session.goto_max()
        return self._state()

    async def screenshot(self) -> bytes:
        await self.ensure_started()
        assert self.session.page is not None
        return await self.session.page.screenshot(type="png", full_page=False)

    async def state(self) -> dict:
        await self.ensure_started()
        return self._state()

    def _state(self) -> dict:
        page = self.session.page
        if not page:
            return {"headful": self.session.headful, "url": None, "title": None}
        return {
            "headful": self.session.headful,
            "url": page.url,
            "title": page.url,  # title() — async, поэтому URL как fallback
        }

    async def click(self, x: int, y: int, button: str = "left") -> None:
        await self.ensure_started()
        assert self.session.page is not None
        await self.session.page.mouse.click(x, y, button=button)

    async def type_text(self, text: str, delay: float = 0.0) -> None:
        await self.ensure_started()
        assert self.session.page is not None
        if delay > 0:
            await self.session.page.keyboard.type(text, delay=delay * 1000)
        else:
            await self.session.page.keyboard.type(text)

    async def press_key(self, key: str) -> None:
        await self.ensure_started()
        assert self.session.page is not None
        # Разрешаем как "Enter", так и "enter"
        norm = key if key in _VALID_KEYS else key.capitalize()
        await self.session.page.keyboard.press(norm)

    async def fill(self, selector: str, value: str) -> None:
        await self.ensure_started()
        assert self.session.page is not None
        await self.session.page.fill(selector, value)

    async def wait_selector(self, selector: str, timeout: float = 10.0) -> bool:
        await self.ensure_started()
        assert self.session.page is not None
        try:
            await self.session.page.wait_for_selector(selector, timeout=timeout * 1000, state="visible")
            return True
        except Exception:
            return False

    async def evaluate(self, script: str) -> Any:
        await self.ensure_started()
        assert self.session.page is not None
        return await self.session.page.evaluate(script)

    async def url(self) -> str:
        await self.ensure_started()
        assert self.session.page is not None
        return self.session.page.url

    async def navigate(self, url: str) -> None:
        await self.ensure_started()
        assert self.session.page is not None
        await self.session.page.goto(url, wait_until="domcontentloaded", timeout=60000)

    async def reload(self) -> None:
        await self.ensure_started()
        assert self.session.page is not None
        await self.session.page.reload(wait_until="domcontentloaded")

    async def back(self) -> None:
        await self.ensure_started()
        assert self.session.page is not None
        await self.session.page.go_back(wait_until="domcontentloaded")

    async def forward(self) -> None:
        await self.ensure_started()
        assert self.session.page is not None
        await self.session.page.go_forward(wait_until="domcontentloaded")

    async def scroll(self, delta_y: int = 300) -> None:
        await self.ensure_started()
        assert self.session.page is not None
        await self.session.page.mouse.wheel(0, delta_y)

    async def cookies(self) -> list[dict]:
        await self.ensure_started()
        assert self.session.context is not None
        return await self.session.context.cookies()

    async def clear_cookies(self) -> None:
        await self.ensure_started()
        assert self.session.context is not None
        await self.session.context.clear_cookies()