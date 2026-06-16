"""Главный цикл воркера: поднимает браузер, логинит, слушает, отправляет.

Также поддерживает headful-режим (ручное управление через Telegram/noVNC).
При входе в headful listener приостанавливается, при выходе — продолжается.
"""

from __future__ import annotations

import asyncio
import logging
import time

from app.api_client import watcher_api
from app.auth import ensure_logged_in, is_logged_in
from app.browser import BrowserSession
from app.config import settings
from app.headful import HeadfulController
from app.listener import MessageListener
from app.sender import send_file, send_text

logger = logging.getLogger(__name__)


class WatcherSupervisor:
    def __init__(self) -> None:
        self.session = BrowserSession()
        self.headful = HeadfulController(self.session)  # шарят один session
        self.listener: MessageListener | None = None
        self._stop = asyncio.Event()
        self._last_health: float = 0
        # Если True — цикл только обрабатывает send-queue, listener выключен.
        # В этом режиме браузер работает в headful, им управляет пользователь.
        self._headful_mode = False

    async def run(self) -> None:
        await watcher_api.post_auth_state("starting")
        backoff = 5
        while not self._stop.is_set():
            try:
                await self._cycle()
                backoff = 5
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover
                logger.exception("Watcher cycle crashed: %s", exc)
                await watcher_api.post_auth_state("error", str(exc))
                await asyncio.sleep(min(60, backoff))
                backoff = min(60, backoff * 2)
            finally:
                await self._teardown()

    async def stop(self) -> None:
        self._stop.set()
        await self._teardown()

    async def _teardown(self) -> None:
        if self.listener:
            try:
                await self.listener.stop()
            except Exception:
                pass
            self.listener = None
        try:
            await self.session.close()
        except Exception:
            pass

    async def _cycle(self) -> None:
        await self.session.start()
        assert self.session.page is not None
        page = self.session.page

        await self.session.goto_max()
        await ensure_logged_in(page)
        await watcher_api.post_auth_state("ok")

        self.listener = MessageListener(page)
        await self.listener.install()
        await self.listener.start()
        logger.info("Watcher cycle running (headful=%s)", self.session.headful)

        while not self._stop.is_set():
            if not self._headful_mode:
                # В обычном режиме — health-check и обработка send-очереди
                await self._maybe_health()
                await self._maybe_process_send_queue()
            else:
                # В headful-режиме — только обрабатываем отправки,
                # listener выключен (его выключил set_headful_true)
                await self._maybe_process_send_queue()
                # Чуть реже, чтобы не молотить зря
                await asyncio.sleep(max(1.0, settings.watcher_poll_interval * 2))
                continue
            await asyncio.sleep(settings.watcher_poll_interval)

    async def _maybe_health(self) -> None:
        now = time.time()
        if now - self._last_health < settings.watcher_health_interval:
            return
        self._last_health = now
        alive = await self.session.alive()
        if not alive:
            raise RuntimeError("Browser not alive")
        try:
            if self.session.page and not await is_logged_in(self.session.page):
                await ensure_logged_in(self.session.page)
        except Exception as exc:
            logger.warning("health: reauth check failed: %s", exc)

    async def _maybe_process_send_queue(self) -> None:
        assert self.session.page is not None
        try:
            cmd = await watcher_api.claim_next_send()
        except Exception as exc:  # pragma: no cover
            logger.warning("claim_next_send failed: %s", exc)
            return
        if not cmd:
            return
        item_id = int(cmd["id"])
        kind = cmd.get("kind", "text")
        chat_id = cmd.get("target_chat_id")
        text = cmd.get("text")
        media_path = cmd.get("media_path")
        try:
            if kind == "text":
                await send_text(self.session.page, chat_id, text or "")
            elif kind in ("photo", "video", "voice", "video_note", "document", "audio", "sticker"):
                if not media_path:
                    raise RuntimeError(f"Нет media_path для {kind}")
                await send_file(self.session.page, chat_id, media_path, caption=text, kind=kind)
            else:
                raise RuntimeError(f"Неизвестный kind: {kind}")
            await watcher_api.finish_send(item_id, ok=True)
            logger.info("send %s to %s ok", kind, chat_id)
        except Exception as exc:
            logger.warning("send failed: %s", exc)
            await watcher_api.finish_send(item_id, ok=False, error=str(exc))

    # ----- Headful-mode API (для /watcher/headful/* endpoints) -----

    async def enter_headful(self) -> dict:
        """Переключает браузер в headful (если ещё не) и приостанавливает listener."""
        self._headful_mode = True
        # Останавливаем listener, чтобы он не натворил дел, пока пользователь
        # вводит логин/пароль руками
        if self.listener:
            try:
                await self.listener.stop()
            except Exception:
                pass
            self.listener = None
        # Если watcher ещё не успел стартовать цикл — это нормально,
        # HeadfulController сам всё поднимет лениво.
        try:
            res = await self.headful.set_headful(True)
        except Exception as exc:
            self._headful_mode = False
            raise RuntimeError(f"Не удалось переключить в headful: {exc}")
        # Открываем MAX, чтобы пользователь сразу видел форму
        try:
            await self.headful.goto_max()
        except Exception as exc:
            logger.warning("goto_max в headful не удалось: %s", exc)
        return res

    async def exit_headful(self) -> dict:
        """Возвращает watcher в headless-режим и переустанавливает listener."""
        self._headful_mode = False
        res = await self.headful.set_headful(False)
        # Если мы были залогинены — listener переустановится на следующем
        # тике основного цикла (он сам управляет self.listener)
        return res


# Синглтон — supervisor создаётся при первом обращении к API.
_supervisor: WatcherSupervisor | None = None


def get_supervisor() -> WatcherSupervisor:
    global _supervisor
    if _supervisor is None:
        _supervisor = WatcherSupervisor()
    return _supervisor


async def main() -> None:
    sup = get_supervisor()
    try:
        await sup.run()
    except asyncio.CancelledError:
        pass
    finally:
        await sup.stop()
        await watcher_api.close()


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(main())