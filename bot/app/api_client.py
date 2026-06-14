"""Клиент к внутреннему API моста (используется ботом)."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from shared.api_auth import ApiClient

from app.config import settings

logger = logging.getLogger(__name__)


class BotApi:
    def __init__(self) -> None:
        self._client = ApiClient(api_key=settings.bridge_api_key)

    async def close(self) -> None:
        await self._client.close()

    async def list_undelivered(self, limit: int = 50) -> List[Dict[str, Any]]:
        return await self._client.list_undelivered(limit=limit)

    async def list_events_for_chat(self, chat_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        return await self._client.list_events_for_chat(chat_id, limit=limit)

    async def mark_delivered(self, event_id: int) -> None:
        await self._client.mark_delivered(event_id)

    async def list_chats(self) -> List[Dict[str, Any]]:
        return await self._client.list_chats()

    async def enqueue_send(
        self,
        target_chat_id: str,
        kind: str,
        text: Optional[str] = None,
        media_path: Optional[str] = None,
        media_mime: Optional[str] = None,
        media_filename: Optional[str] = None,
        created_by: Optional[int] = None,
    ) -> Dict[str, Any]:
        payload = {
            "target_chat_id": target_chat_id,
            "kind": kind,
            "text": text,
            "media_path": media_path,
            "media_mime": media_mime,
            "media_filename": media_filename,
            "created_by": created_by,
        }
        return await self._client.enqueue_send(payload)

    async def status(self) -> Dict[str, Any]:
        return await self._client.status()

    async def post_2fa_code(self, request_id: int, code: str) -> None:
        await self._client.put_2fa(request_id, code)

    async def request_2fa(self) -> int:
        """Сообщает watcher, что нужен новый 2FA (используется, когда текущий истёк)."""

        import httpx
        async with httpx.AsyncClient(base_url=self._client.base_url, timeout=10.0) as c:
            r = await c.post("/auth/2fa/request", headers=self._client._headers())
            r.raise_for_status()
            return r.json()["request_id"]


api = BotApi()