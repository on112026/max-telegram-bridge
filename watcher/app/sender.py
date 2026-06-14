"""Отправка сообщений в MAX через Playwright."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Optional

from playwright.async_api import Page

from app.config import settings

logger = logging.getLogger(__name__)


# Селекторы для чат-листа, инпута сообщения, поля для аттача.
CHAT_ITEM_SELECTORS = [
    "[data-testid='chat-list'] [data-testid='chat']",
    "[data-testid='conversation']",
    "div[role='listitem'][data-id]",
    "a[href*='/chat/']",
    ".chat-item",
    ".conversation-item",
]

MESSAGE_INPUT_SELECTORS = [
    "[data-testid='message-input']",
    "div[contenteditable='true'][data-role='input']",
    "div[contenteditable='true'].ProseMirror",
    "textarea[placeholder*='сообщ' i]",
    "textarea[placeholder*='message' i]",
    "textarea",
]

FILE_INPUT_SELECTORS = [
    "input[type='file'][accept*='image']",
    "input[type='file'][accept*='video']",
    "input[type='file']",
]

SEND_BUTTON_SELECTORS = [
    "[data-testid='send-button']",
    "button[aria-label*='отправ' i]",
    "button[aria-label*='send' i]",
    "button[type='submit']",
    "button.send",
]


async def _click_first(page: Page, selectors, timeout: float = 5000) -> bool:
    for sel in selectors:
        try:
            el = await page.wait_for_selector(sel, timeout=timeout, state="visible")
            if el:
                await el.click()
                return True
        except Exception:
            continue
    return False


async def open_chat(page: Page, chat_id: str) -> bool:
    """Пытаемся открыть чат по его id через клик в боковом списке.

    Если не нашли по селектору — пробуем перейти по URL вида /chat/<id>.
    """

    # Сначала ищем data-id / data-chat-id
    candidates = [
        f"[data-id='{chat_id}']",
        f"[data-chat-id='{chat_id}']",
        f"[data-conversation-id='{chat_id}']",
    ]
    for sel in candidates:
        try:
            el = await page.query_selector(sel)
            if el:
                await el.click()
                await asyncio.sleep(0.5)
                return True
        except Exception:
            continue
    # Иначе — пробуем кликнуть по любому элементу, содержащему id в атрибутах
    try:
        el = await page.query_selector(f"[data-id*='{chat_id}']")
        if el:
            await el.click()
            return True
    except Exception:
        pass
    # Прямой переход по URL
    try:
        url = f"{settings.max_web_url.rstrip('/')}/chat/{chat_id}"
        await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        await asyncio.sleep(0.5)
        return True
    except Exception as exc:
        logger.warning("open_chat fallback URL failed: %s", exc)
    return False


async def _paste_text(page: Page, text: str) -> bool:
    """Вставляет текст в инпут сообщения. Используем contenteditable + execCommand,
    запасной вариант — clipboard API."""

    el = None
    for sel in MESSAGE_INPUT_SELECTORS:
        try:
            el = await page.wait_for_selector(sel, timeout=5000, state="visible")
            if el:
                break
        except Exception:
            continue
    if not el:
        return False
    try:
        tag = await el.evaluate("e => e.tagName.toLowerCase()")
    except Exception:
        tag = ""
    try:
        if tag in ("textarea", "input"):
            await el.fill(text)
        else:
            # contenteditable
            await el.click()
            await el.evaluate(
                "(el, t) => { el.focus(); el.innerText = t; el.dispatchEvent(new InputEvent('input', { bubbles: true })); }",
                text,
            )
        return True
    except Exception as exc:
        logger.warning("paste text failed: %s", exc)
        return False


async def _send(page: Page) -> bool:
    # Сначала пробуем Enter (надёжнее всего)
    try:
        await page.keyboard.press("Enter")
        return True
    except Exception:
        pass
    return await _click_first(page, SEND_BUTTON_SELECTORS, timeout=2000)


async def _attach_file(page: Page, path: str, kind: str) -> bool:
    """Прикрепляет файл через input[type=file] и (для фото) отправляет без подписи."""

    full = path
    if not os.path.isabs(full):
        full = os.path.join(settings.media_dir, path)
    if not os.path.exists(full):
        logger.warning("media file not found: %s", full)
        return False
    file_input = None
    for sel in FILE_INPUT_SELECTORS:
        try:
            file_input = await page.query_selector(sel)
            if file_input:
                break
        except Exception:
            continue
    if not file_input:
        # Возможно, нужно открыть диалог "+" и дождаться появления input
        if await _click_first(
            page,
            [
                "[data-testid='attach-button']",
                "button[aria-label*='прикрепить' i]",
                "button[aria-label*='attach' i]",
            ],
            timeout=2000,
        ):
            await asyncio.sleep(0.3)
            for sel in FILE_INPUT_SELECTORS:
                try:
                    file_input = await page.wait_for_selector(sel, timeout=3000, state="attached")
                    if file_input:
                        break
                except Exception:
                    continue
    if not file_input:
        logger.warning("file input not found")
        return False
    try:
        await file_input.set_input_files(full)
    except Exception as exc:
        logger.warning("set_input_files failed: %s", exc)
        return False
    await asyncio.sleep(0.7)
    return True


async def send_text(page: Page, chat_id: str, text: str) -> None:
    if not await open_chat(page, chat_id):
        raise RuntimeError(f"Не удалось открыть чат {chat_id}")
    if not await _paste_text(page, text):
        raise RuntimeError("Не удалось ввести текст в поле сообщения MAX")
    if not await _send(page):
        raise RuntimeError("Не удалось отправить сообщение в MAX")
    await asyncio.sleep(0.3)


async def send_file(
    page: Page,
    chat_id: str,
    path: str,
    caption: Optional[str] = None,
    kind: str = "document",
) -> None:
    if not await open_chat(page, chat_id):
        raise RuntimeError(f"Не удалось открыть чат {chat_id}")
    if not await _attach_file(page, path, kind):
        raise RuntimeError("Не удалось прикрепить файл в MAX")
    if caption:
        # Подпись вставляется в input сообщения после прикрепления
        if not await _paste_text(page, caption):
            logger.warning("Не удалось добавить подпись")
    if not await _send(page):
        raise RuntimeError("Не удалось отправить файл в MAX")
    await asyncio.sleep(0.5)