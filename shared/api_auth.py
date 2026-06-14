"""HTTP-клиент и зависимости авторизации для внутренних вызовов API."""

from __future__ import annotations

import os
from typing import Optional

import httpx
from fastapi import Header, HTTPException, status


def api_base_url() -> str:
    # Контейнеры общаются по имени сервиса в compose
    host = os.getenv("API_HOST_INTERNAL", "api")
    port = int(os.getenv("API_PORT", "8000"))
    return f"http://{host}:{port}"


async def verify_api_key(x_api_key: Optional[str] = Header(default=None)) -> None:
    expected = os.getenv("BRIDGE_API_KEY", "")
    if not expected:
        # Если ключ не задан на стороне API, откажем всем
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "API key not configured")
    if not x_api_key or x_api_key != expected:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key")


class ApiClient:
    """Тонкая обёртка над httpx."""

    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None) -> None:
        self.base_url = base_url or api_base_url()
        self.api_key = api_key or os.getenv("BRIDGE_API_KEY", "")
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=30.0)

    async def close(self) -> None:
        await self._client.aclose()

    def _headers(self) -> dict:
        return {"X-Api-Key": self.api_key}

    async def post_event(self, event: dict) -> dict:
        r = await self._client.post("/events", json=event, headers=self._headers())
        r.raise_for_status()
        return r.json()

    async def post_chat(self, chat: dict) -> dict:
        r = await self._client.post("/chats", json=chat, headers=self._headers())
        r.raise_for_status()
        return r.json()

    async def list_undelivered(self, limit: int = 50) -> list:
        r = await self._client.get(
            "/events", params={"undelivered": "1", "limit": str(limit)}, headers=self._headers()
        )
        r.raise_for_status()
        return r.json()

    async def list_events_for_chat(self, chat_id: str, limit: int = 20) -> list:
        r = await self._client.get(
            f"/events/by-chat/{chat_id}",
            params={"limit": str(limit)},
            headers=self._headers(),
        )
        r.raise_for_status()
        return r.json()

    async def mark_delivered(self, event_id: int) -> None:
        r = await self._client.post(
            f"/events/{event_id}/delivered", headers=self._headers()
        )
        r.raise_for_status()

    async def list_chats(self) -> list:
        r = await self._client.get("/chats", headers=self._headers())
        r.raise_for_status()
        return r.json()

    async def enqueue_send(self, payload: dict) -> dict:
        r = await self._client.post("/send", json=payload, headers=self._headers())
        r.raise_for_status()
        return r.json()

    async def get_send(self, item_id: int) -> dict:
        r = await self._client.get(f"/send/{item_id}", headers=self._headers())
        r.raise_for_status()
        return r.json()

    async def put_2fa(self, request_id: int, code: str) -> dict:
        r = await self._client.post(
            "/auth/2fa",
            json={"request_id": request_id, "code": code},
            headers=self._headers(),
        )
        r.raise_for_status()
        return r.json()

    async def status(self) -> dict:
        r = await self._client.get("/status", headers=self._headers())
        r.raise_for_status()
        return r.json()