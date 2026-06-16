"""Клиент к внутреннему API моста."""

from __future__ import annotations

import asyncio
import logging

from shared.http_client import ApiClient

from app.config import settings

logger = logging.getLogger(__name__)


class WatcherApi:
    def __init__(self) -> None:
        self._client = ApiClient(api_key=settings.bridge_api_key)

    async def close(self) -> None:
        await self._client.close()

    # events / chats
    async def post_event(self, event: dict) -> None:
        try:
            await self._client.post_event(event)
        except Exception as exc:  # pragma: no cover
            logger.warning("post_event failed: %s", exc)

    async def post_chat(self, chat: dict) -> None:
        try:
            await self._client.post_chat(chat)
        except Exception as exc:  # pragma: no cover
            logger.warning("post_chat failed: %s", exc)

    async def post_auth_state(self, status: str, error: str | None = None) -> None:
        try:
            import httpx
            async with httpx.AsyncClient(base_url=self._client.base_url, timeout=10.0) as c:
                await c.post(
                    "/auth/state",
                    json={"status": status, "error": error},
                    headers=self._client._headers(),
                )
        except Exception as exc:  # pragma: no cover
            logger.warning("post_auth_state failed: %s", exc)

    async def open_2fa_request(self) -> int:
        try:
            import httpx
            async with httpx.AsyncClient(base_url=self._client.base_url, timeout=10.0) as c:
                r = await c.post("/auth/2fa/request", headers=self._client._headers())
                r.raise_for_status()
                return r.json()["request_id"]
        except Exception as exc:  # pragma: no cover
            logger.warning("open_2fa_request failed: %s", exc)
            return 0

    async def peek_2fa(self, request_id: int) -> str | None:
        try:
            import httpx
            async with httpx.AsyncClient(base_url=self._client.base_url, timeout=10.0) as c:
                r = await c.get(f"/auth/2fa/peek/{request_id}", headers=self._client._headers())
                r.raise_for_status()
                data = r.json()
                return data.get("code")
        except Exception as exc:  # pragma: no cover
            logger.warning("peek_2fa failed: %s", exc)
            return None

    # send queue
    async def claim_next_send(self) -> dict | None:
        try:
            r = await self._client._client.get("/send/next", headers=self._client._headers())
            r.raise_for_status()
            if r.status_code == 204:
                return None
            text = (r.text or "").strip()
            if not text:
                return None
            import json
            data = json.loads(text)
            if not data:
                return None
            return data
        except Exception as exc:  # pragma: no cover
            logger.warning("claim_next_send failed: %s", exc)
            return None

    async def finish_send(self, item_id: int, ok: bool, error: str | None = None) -> None:
        try:
            r = await self._client._client.post(
                f"/send/{item_id}/finish",
                params={"ok": "true" if ok else "false", "error": error or ""},
                headers=self._client._headers(),
            )
            r.raise_for_status()
        except Exception as exc:  # pragma: no cover
            logger.warning("finish_send failed: %s", exc)


watcher_api = WatcherApi()