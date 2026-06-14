"""Слушатель новых сообщений MAX через WebSocket / XHR / DOM."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from playwright.async_api import Page

from app.api_client import watcher_api

logger = logging.getLogger(__name__)

# JS-сниппет, который ставит ловушки на WebSocket и XHR и складывает «сырые»
# данные в window.__maxBridgeQueue. Обработка/нормализация делается в Python.
INJECT_SCRIPT = r"""
(() => {
  if (window.__maxBridgeInstalled) return;
  window.__maxBridgeInstalled = true;
  window.__maxBridgeQueue = [];
  window.__maxBridgeChats = new Set();
  window.__maxBridgeSeen = new Set();
  window.__maxBridgePushed = new Set();

  const enqueue = (kind, payload) => {
    try {
      window.__maxBridgeQueue.push({ ts: Date.now(), kind, payload });
      if (window.__maxBridgeQueue.length > 5000) {
        window.__maxBridgeQueue.splice(0, window.__maxBridgeQueue.length - 5000);
      }
    } catch (e) { /* ignore */ }
  };

  // WebSocket
  const OrigWS = window.WebSocket;
  function HookWS(url, protocols) {
    const ws = protocols ? new OrigWS(url, protocols) : new OrigWS(url);
    const sockRef = { url };
    try {
      sockRef.url = url;
    } catch (e) {}
    ws.addEventListener('message', (ev) => {
      try { enqueue('ws', { url: sockRef.url, data: typeof ev.data === 'string' ? ev.data : '<binary>' }); }
      catch (e) {}
    });
    return ws;
  }
  HookWS.prototype = OrigWS.prototype;
  Object.defineProperty(HookWS, 'name', { value: 'WebSocket' });
  window.WebSocket = HookWS;

  // XHR
  const OrigXHR = window.XMLHttpRequest;
  class HookXHR extends OrigXHR {
    constructor() {
      super();
      this._url = '';
      this._method = '';
      this._body = null;
      const origOpen = this.open;
      this.open = (method, url, ...rest) => {
        this._method = method;
        this._url = url;
        return origOpen.call(this, method, url, ...rest);
      };
      const origSend = this.send;
      this.send = (body) => {
        this._body = body;
        return origSend.call(this, body);
      };
      this.addEventListener('load', () => {
        try {
          const txt = this.responseText || '';
          if (txt && (txt[0] === '{' || txt[0] === '[')) {
            enqueue('xhr', { method: this._method, url: this._url, body: this._body, response: txt.slice(0, 200000) });
          } else {
            enqueue('xhr-meta', { method: this._method, url: this._url });
          }
        } catch (e) {}
      });
    }
  }
  window.XMLHttpRequest = HookXHR;

  // fetch
  const origFetch = window.fetch;
  if (origFetch) {
    window.fetch = async function(input, init) {
      const url = typeof input === 'string' ? input : (input && input.url) || '';
      const method = (init && init.method) || 'GET';
      const body = init && init.body;
      const resp = await origFetch.apply(this, arguments);
      try {
        const clone = resp.clone();
        const txt = await clone.text();
        if (txt && (txt[0] === '{' || txt[0] === '[')) {
          enqueue('fetch', { method, url, body: typeof body === 'string' ? body : null, response: txt.slice(0, 200000) });
        } else {
          enqueue('fetch-meta', { method, url });
        }
      } catch (e) {}
      return resp;
    };
  }
})();
"""


CHAT_TITLE_JS = r"""
(() => {
  try {
    const candidates = [
      document.querySelector('header [class*="title" i]')?.textContent || '',
      document.querySelector('header h1, header h2, header h3')?.textContent || '',
      document.querySelector('[data-testid="conversation-title"]')?.textContent || '',
      document.querySelector('.chat-info .title, .conversation-title')?.textContent || '',
    ];
    return candidates.find(t => t && t.trim()) || document.title || null;
  } catch (e) { return null; }
})()
"""


def _looks_like_message(payload: Any) -> Optional[dict]:
    """Попытка извлечь сообщение из произвольного JSON-узла MAX Web."""

    if not isinstance(payload, dict):
        return None
    # Разные верблюды/змейки
    msg_id = (
        payload.get("id")
        or payload.get("messageId")
        or payload.get("message_id")
        or payload.get("msgId")
        or payload.get("msg_id")
    )
    chat_id = (
        payload.get("chatId")
        or payload.get("chat_id")
        or payload.get("conversationId")
        or payload.get("conversation_id")
        or payload.get("peerId")
    )
    if not msg_id or not chat_id:
        # Может быть, payload вложен в { message: {...} } или { data: {...} }
        for k in ("message", "data", "result", "msg", "event"):
            sub = payload.get(k)
            if isinstance(sub, dict):
                inner = _looks_like_message(sub)
                if inner:
                    return inner
        return None
    text = (
        payload.get("text")
        or payload.get("body")
        or payload.get("message")
        or payload.get("content")
    )
    sender = None
    sender_id = None
    sender_obj = payload.get("sender") or payload.get("from") or payload.get("author")
    if isinstance(sender_obj, dict):
        sender = sender_obj.get("name") or sender_obj.get("displayName") or sender_obj.get("title")
        sender_id = str(sender_obj.get("id") or sender_obj.get("userId") or "")
    else:
        sender = payload.get("senderName") or payload.get("fromName")
        sender_id = str(payload.get("senderId") or payload.get("fromId") or "")

    media = payload.get("media") or payload.get("attachment") or payload.get("file")
    media_url = None
    media_mime = None
    media_filename = None
    media_size = None
    kind = "text"
    if isinstance(media, dict):
        media_url = media.get("url") or media.get("src") or media.get("downloadUrl")
        media_mime = media.get("mimeType") or media.get("mime") or media.get("type")
        media_filename = media.get("fileName") or media.get("name")
        media_size = media.get("size") or media.get("fileSize")
        kind = media.get("kind") or _guess_kind(media_mime, media_filename)
    elif isinstance(media, list) and media:
        first = media[0]
        if isinstance(first, dict):
            media_url = first.get("url") or first.get("src")
            media_mime = first.get("mimeType") or first.get("type")
            media_filename = first.get("fileName") or first.get("name")
            media_size = first.get("size")
            kind = _guess_kind(media_mime, media_filename)
    return {
        "max_chat_id": str(chat_id),
        "max_message_id": str(msg_id),
        "text": (text if isinstance(text, str) else None),
        "sender": sender,
        "sender_id": sender_id,
        "media_url": media_url,
        "media_mime": media_mime,
        "media_filename": media_filename,
        "media_size": media_size,
        "kind": kind,
        "ts": payload.get("timestamp") or payload.get("ts") or payload.get("date"),
        "is_outgoing": bool(payload.get("outgoing") or payload.get("fromMe")),
    }


def _guess_kind(mime: str | None, filename: str | None) -> str:
    m = (mime or "").lower()
    fn = (filename or "").lower()
    if m.startswith("image/"):
        return "photo"
    if m.startswith("video/"):
        if "round" in fn or "circle" in fn or "note" in fn:
            return "video_note"
        return "video"
    if m.startswith("audio/"):
        if "ogg" in m or "opus" in m:
            return "voice"
        return "audio"
    if "sticker" in fn:
        return "sticker"
    if m == "application/octet-stream" or m.startswith("application/") or m:
        return "document"
    return "text"


class MessageListener:
    """Слушает браузерную очередь, нормализует, публикует в API."""

    def __init__(self, page: Page) -> None:
        self.page = page
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()
        self._last_poll: Dict[str, float] = {}
        self._last_dom_chat: Optional[str] = None

    async def install(self) -> None:
        await self.page.add_init_script(INJECT_SCRIPT)
        # Если страница уже загружена — сразу поставим
        try:
            await self.page.evaluate(INJECT_SCRIPT)
        except Exception:
            pass
        logger.info("Listener scripts installed")

    async def start(self) -> None:
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="max-bridge-listener")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5)
            except Exception:
                self._task.cancel()
            self._task = None

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self._tick()
            except Exception as exc:  # pragma: no cover
                logger.warning("listener tick error: %s", exc)
            await asyncio.sleep(0.8)

    async def _tick(self) -> None:
        items = await self.page.evaluate("() => (window.__maxBridgeQueue || []).splice(0)")
        for item in items:
            try:
                await self._handle_item(item)
            except Exception as exc:  # pragma: no cover
                logger.debug("handle_item error: %s", exc)

        # DOM-fallback: раз в несколько секунд читаем заголовок текущего чата
        now = time.time()
        if now - self._last_dom_chat_ts() > 5:
            try:
                title = await self.page.evaluate(CHAT_TITLE_JS)
                if title and isinstance(title, str) and title.strip():
                    self._last_dom_chat = title.strip()
            except Exception:
                pass

    def _last_dom_chat_ts(self) -> float:
        return getattr(self, "_last_dom_ts", 0.0) or 0.0

    async def _handle_item(self, item: dict) -> None:
        kind = item.get("kind")
        payload = item.get("payload") or {}
        if kind in ("ws", "xhr", "fetch"):
            # Парсим JSON из response / data
            text = None
            if kind == "ws":
                text = payload.get("data")
            else:
                text = payload.get("response")
            if not text or not isinstance(text, str):
                return
            try:
                obj = json.loads(text)
            except Exception:
                return
            await self._parse_obj(obj, kind_hint=kind)
        elif kind in ("xhr-meta", "fetch-meta"):
            return

    async def _parse_obj(self, obj: Any, kind_hint: str = "") -> None:
        # obj может быть списком событий
        candidates: List[Any] = []
        if isinstance(obj, list):
            candidates.extend(obj)
        elif isinstance(obj, dict):
            # возможные обёртки
            for k in ("messages", "events", "items", "data", "result", "updates"):
                v = obj.get(k)
                if isinstance(v, list):
                    candidates.extend(v)
                elif isinstance(v, dict):
                    candidates.append(v)
            candidates.append(obj)
        for cand in candidates:
            msg = _looks_like_message(cand)
            if not msg:
                continue
            await self._publish(msg)

    async def _publish(self, msg: dict) -> None:
        chat_id = msg["max_chat_id"]
        # дедупликация в браузере
        seen_key = f"{chat_id}:{msg['max_message_id']}"
        already = await self.page.evaluate(
            "key => { const s = window.__maxBridgeSeen || (window.__maxBridgeSeen = new Set()); if (s.has(key)) return true; s.add(key); if (s.size > 5000) { const arr = Array.from(s).slice(-2000); window.__maxBridgeSeen = new Set(arr);} return false; }",
            seen_key,
        )
        if already:
            return
        event = {
            "max_chat_id": chat_id,
            "max_message_id": msg["max_message_id"],
            "sender": msg.get("sender"),
            "sender_id": msg.get("sender_id"),
            "text": msg.get("text"),
            "kind": msg.get("kind") or "text",
            "media_url": msg.get("media_url"),
            "media_mime": msg.get("media_mime"),
            "media_filename": msg.get("media_filename"),
            "media_size": msg.get("media_size"),
            "timestamp": msg.get("ts"),
            "is_outgoing": bool(msg.get("is_outgoing")),
            "chat_title": self._last_dom_chat,
        }
        await watcher_api.post_event(event)
        if self._last_dom_chat:
            await watcher_api.post_chat(
                {
                    "max_chat_id": chat_id,
                    "title": self._last_dom_chat,
                    "last_message_at": event.get("timestamp"),
                    "last_message_preview": (msg.get("text") or "")[:200],
                }
            )
        logger.info(
            "event: chat=%s msg=%s kind=%s text=%r",
            chat_id,
            msg["max_message_id"],
            event["kind"],
            (msg.get("text") or "")[:120],
        )