"""Авторизация в MAX Web: первичная настройка, логин, 2FA."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Optional

import pyotp
from playwright.async_api import Page

from app.api_client import watcher_api
from app.config import settings

logger = logging.getLogger(__name__)


# Кандидаты селекторов MAX Web. Сайт часто меняет вёрстку, поэтому в коде
# используется несколько фолбэков.
PHONE_INPUTS = [
    "input[name='phone']",
    "input[type='tel']",
    "input[autocomplete='tel']",
    "input[data-testid='phone']",
    "input[placeholder*='телефон' i]",
    "input[placeholder*='phone' i]",
]
PASSWORD_INPUTS = [
    "input[name='password']",
    "input[type='password']",
    "input[data-testid='password']",
]
CODE_INPUTS = [
    "input[name='code']",
    "input[name='otp']",
    "input[type='tel']",
    "input[inputmode='numeric']",
    "input[autocomplete='one-time-code']",
]
LOGIN_BUTTONS = [
    "button[type='submit']",
    "button:has-text('Войти')",
    "button:has-text('Continue')",
    "button:has-text('Login')",
    "button:has-text('Продолжить')",
]


async def _fill_first(page: Page, selectors: list[str], value: str, timeout: float = 5000) -> bool:
    for sel in selectors:
        try:
            el = await page.wait_for_selector(sel, timeout=timeout, state="visible")
            if el:
                await el.fill("")
                await el.fill(value)
                return True
        except Exception:
            continue
    return False


async def _click_first(page: Page, selectors: list[str], timeout: float = 5000) -> bool:
    for sel in selectors:
        try:
            el = await page.wait_for_selector(sel, timeout=timeout, state="visible")
            if el:
                await el.click()
                return True
        except Exception:
            continue
    return False


async def is_logged_in(page: Page) -> bool:
    """Грубая эвристика: после логина виден список чатов/боковая панель."""

    # Пробуем найти любой признак чат-листа
    candidates = [
        "[data-testid='chat-list']",
        "[data-testid='conversation-list']",
        "nav[aria-label*='чат' i]",
        "div[role='navigation']",
        "aside",
    ]
    for sel in candidates:
        try:
            el = await page.query_selector(sel)
            if el:
                return True
        except Exception:
            continue
    # Если на странице виден инпут для пароля — точно не залогинены
    for sel in PASSWORD_INPUTS:
        try:
            el = await page.query_selector(sel)
            if el:
                return False
        except Exception:
            continue
    # Не нашли явных признаков — лучше считать, что залогинены
    return True


async def perform_login(page: Page) -> None:
    """Шаг логина: телефон + пароль."""

    ok_phone = await _fill_first(page, PHONE_INPUTS, settings.max_phone, timeout=10000)
    if not ok_phone:
        # Возможно, форма уже частично заполнена — пропускаем
        logger.info("Phone input not found — assuming already filled")
    await asyncio.sleep(0.3)
    ok_pass = await _fill_first(page, PASSWORD_INPUTS, settings.max_password, timeout=10000)
    if not ok_pass:
        raise RuntimeError("Не нашли поле пароля на странице логина MAX")
    await asyncio.sleep(0.2)
    if not await _click_first(page, LOGIN_BUTTONS, timeout=5000):
        raise RuntimeError("Не нашли кнопку входа в MAX")
    await asyncio.sleep(2)


async def handle_2fa(page: Page) -> bool:
    """Если MAX показал 2FA — вводим код (TOTP из .env или запрошенный у владельца)."""

    has_code_field = False
    for sel in CODE_INPUTS:
        try:
            el = await page.query_selector(sel)
            if el:
                has_code_field = True
                break
        except Exception:
            continue
    if not has_code_field:
        return False

    request_id = await watcher_api.open_2fa_request()
    code: Optional[str] = None
    if settings.max_totp_secret:
        try:
            code = pyotp.TOTP(settings.max_totp_secret).now()
            logger.info("2FA code generated from TOTP secret")
        except Exception as exc:
            logger.warning("Не удалось сгенерировать TOTP: %s", exc)
    if not code and request_id:
        # Ждём, пока владелец пришлёт код через Telegram-бота
        for _ in range(120):  # 2 минуты
            code = await watcher_api.peek_2fa(request_id)
            if code:
                break
            await asyncio.sleep(1)
    if not code:
        raise RuntimeError("2FA-код не получен в течение 2 минут")
    ok = await _fill_first(page, CODE_INPUTS, code, timeout=5000)
    if not ok:
        raise RuntimeError("Не удалось ввести 2FA-код в MAX")
    await _click_first(page, LOGIN_BUTTONS, timeout=5000)
    await asyncio.sleep(2)
    return True


async def ensure_logged_in(page: Page) -> None:
    """Гарантирует авторизованное состояние, при необходимости — логинит."""

    if await is_logged_in(page):
        await watcher_api.post_auth_state("ok")
        return

    logger.info("Not logged in — attempting login")
    await watcher_api.post_auth_state("need_reauth")
    try:
        await perform_login(page)
    except Exception as exc:
        await watcher_api.post_auth_state("need_reauth", str(exc))
        raise
    try:
        if await handle_2fa(page):
            logger.info("2FA handled")
    except Exception as exc:
        await watcher_api.post_auth_state("need_2fa", str(exc))
        raise
    # Проверяем, что вошли
    for _ in range(20):
        if await is_logged_in(page):
            await watcher_api.post_auth_state("ok")
            return
        await asyncio.sleep(1)
    await watcher_api.post_auth_state("need_reauth", "login check timeout")
    raise RuntimeError("Не удалось подтвердить успешный логин MAX")


async def setup() -> None:
    """CLI-утилита для интерактивной первичной авторизации.

    Запускается командой ``python -m app.auth --setup``.
    """

    from app.browser import BrowserSession

    session = BrowserSession()
    os.environ["HEADFUL"] = "1"
    await session.start()
    await session.goto_max()
    print(
        "Открыт MAX Web в реальном окне. Войдите в аккаунт вручную.\n"
        "Если включена 2FA — введите код из MAX.\n"
        "После загрузки чатов закройте окно браузера и нажмите Enter."
    )
    try:
        input("Нажмите Enter для завершения сессии...")
    finally:
        await session.close()


if __name__ == "__main__":  # pragma: no cover
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--setup", action="store_true")
    args = parser.parse_args()
    if args.setup:
        asyncio.run(setup())
    else:
        print("Используйте --setup")