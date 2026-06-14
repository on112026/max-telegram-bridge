"""Главный цикл воркера: поднимает браузер, логинит, слушает, отправляет."""

from __future__ import annotations

import asyncio
import logging
import time

from app.api_client import watcher_api
from app.auth import ensure_logged_in, is_logged_in
from app.browser import BrowserSession
from app.config import settings
from app.listener import MessageListener
from app.sender import send_file, send_text

logger = logging.getLogger(__name__)


class WatcherSupervisor:
    def __init__(self) -> None:
        self.session = BrowserSession()
        self.listener: MessageListener | None = None
        self._stop = asyncio.Event()
        self._last_health: float = 0

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
        logger.info("Watcher cycle running")

        while not self._stop.is_set():
            await self._maybe_health()
            await self._maybe_process_send_queue()
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


async def main() -> None:
    sup = WatcherSupervisor()
    try:
        await sup.run()
    except asyncio.CancelledError:
        pass
    finally:
        await sup.stop()
        await watcher_api.close()


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(main())