"""FastAPI-приложение моста MAX ↔ Telegram."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Подключаем /app/shared, /app/api как путь импорта
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared"))
sys.path.insert(0, str(ROOT / "api"))

from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from pydantic import BaseModel

from shared import db, models
from shared.api_auth import verify_api_key
from shared.config import load_settings
from shared.log_setup import configure_logging


settings = load_settings()
configure_logging(settings.log_level)
db.init_engine(settings.db_path)


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_engine(settings.db_path)
    os.makedirs(settings.media_dir, exist_ok=True)
    yield


app = FastAPI(title="MAX ↔ Telegram Bridge API", version="1.0.0", lifespan=lifespan)


# ---------- Схемы запросов/ответов ----------


class EventIn(BaseModel):
    max_chat_id: str
    max_message_id: str
    chat_title: Optional[str] = None
    sender: Optional[str] = None
    sender_id: Optional[str] = None
    text: Optional[str] = None
    kind: str = "text"
    media_path: Optional[str] = None
    media_mime: Optional[str] = None
    media_filename: Optional[str] = None
    media_size: Optional[int] = None
    timestamp: Optional[str] = None
    is_outgoing: bool = False


class EventOut(BaseModel):
    id: int
    max_chat_id: str
    max_message_id: str
    chat_title: Optional[str] = None
    sender: Optional[str] = None
    sender_id: Optional[str] = None
    text: Optional[str] = None
    kind: str
    media_path: Optional[str] = None
    media_mime: Optional[str] = None
    media_filename: Optional[str] = None
    media_size: Optional[int] = None
    timestamp: Optional[str] = None
    is_outgoing: bool


class ChatIn(BaseModel):
    max_chat_id: str
    title: Optional[str] = None
    type: Optional[str] = None
    last_message_preview: Optional[str] = None
    last_message_at: Optional[str] = None
    unread: Optional[int] = None


class ChatOut(BaseModel):
    max_chat_id: str
    title: Optional[str] = None
    type: Optional[str] = None
    last_message_preview: Optional[str] = None
    last_message_at: Optional[str] = None
    unread: Optional[int] = None


class SendIn(BaseModel):
    kind: str = "text"
    target_chat_id: str
    text: Optional[str] = None
    media_path: Optional[str] = None
    media_mime: Optional[str] = None
    media_filename: Optional[str] = None
    created_by: Optional[int] = None


class SendOut(BaseModel):
    id: int
    kind: str
    target_chat_id: str
    text: Optional[str] = None
    media_path: Optional[str] = None
    media_mime: Optional[str] = None
    media_filename: Optional[str] = None
    status: str
    error: Optional[str] = None
    created_at: Optional[str] = None
    finished_at: Optional[str] = None


class StatusOut(BaseModel):
    auth: dict
    queue: dict
    undelivered: int
    chats: int


class OkOut(BaseModel):
    ok: bool = True


def _event_to_out(e) -> EventOut:
    return EventOut(
        id=e.id,
        max_chat_id=e.max_chat_id,
        max_message_id=e.max_message_id,
        chat_title=e.chat_title,
        sender=e.sender,
        sender_id=e.sender_id,
        text=e.text,
        kind=e.kind,
        media_path=e.media_path,
        media_mime=e.media_mime,
        media_filename=e.media_filename,
        media_size=e.media_size,
        timestamp=e.ts.isoformat() if e.ts else None,
        is_outgoing=e.is_outgoing,
    )


def _chat_to_out(c) -> ChatOut:
    return ChatOut(
        max_chat_id=c.max_chat_id,
        title=c.title,
        type=c.type,
        last_message_preview=c.last_preview,
        last_message_at=c.last_ts.isoformat() if c.last_ts else None,
        unread=c.unread,
    )


def _send_to_out(s) -> SendOut:
    return SendOut(
        id=s.id,
        kind=s.kind,
        target_chat_id=s.target_chat_id,
        text=s.text,
        media_path=s.media_path,
        media_mime=s.media_mime,
        media_filename=s.media_filename,
        status=s.status,
        error=s.error,
        created_at=s.created_at.isoformat() if s.created_at else None,
        finished_at=s.finished_at.isoformat() if s.finished_at else None,
    )


# ---------- Маршруты ----------


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/events", response_model=OkOut, dependencies=[Depends(verify_api_key)])
def post_event(event: EventIn) -> OkOut:
    payload = event.model_dump()
    if payload.get("timestamp"):
        from datetime import datetime
        try:
            payload["timestamp"] = datetime.fromisoformat(payload["timestamp"].replace("Z", "+00:00"))
        except ValueError:
            payload["timestamp"] = None
    new_id = db.upsert_event(payload)
    return OkOut(ok=True) if new_id is not None else OkOut(ok=True)


@app.get("/events", response_model=List[EventOut], dependencies=[Depends(verify_api_key)])
def list_events(
    undelivered: bool = Query(default=False),
    limit: int = Query(default=20, ge=1, le=200),
) -> List[EventOut]:
    if undelivered:
        rows = db.list_undelivered_events(limit=limit)
    else:
        # Возвращаем последние события (все)
        with db.session_scope() as s:
            from sqlalchemy import select
            rows = (
                s.execute(select(db.Event).order_by(db.Event.ts.desc()).limit(limit))
                .scalars()
                .all()
            )
            s.expunge_all()
            rows = list(rows)
    return [_event_to_out(r) for r in rows]


@app.get("/events/by-chat/{chat_id}", response_model=List[EventOut], dependencies=[Depends(verify_api_key)])
def events_by_chat(chat_id: str, limit: int = Query(default=20, ge=1, le=200)) -> List[EventOut]:
    rows = db.list_events_for_chat(chat_id, limit=limit)
    return [_event_to_out(r) for r in rows]


@app.post("/events/{event_id}/delivered", response_model=OkOut, dependencies=[Depends(verify_api_key)])
def mark_event_delivered(event_id: int) -> OkOut:
    db.mark_event_delivered(event_id)
    return OkOut(ok=True)


@app.post("/chats", response_model=OkOut, dependencies=[Depends(verify_api_key)])
def post_chat(chat: ChatIn) -> OkOut:
    payload = chat.model_dump()
    if payload.get("last_message_at"):
        from datetime import datetime
        try:
            payload["last_message_at"] = datetime.fromisoformat(payload["last_message_at"].replace("Z", "+00:00"))
        except ValueError:
            payload["last_message_at"] = None
    db.upsert_chat(payload)
    return OkOut(ok=True)


@app.get("/chats", response_model=List[ChatOut], dependencies=[Depends(verify_api_key)])
def get_chats(limit: int = Query(default=100, ge=1, le=500)) -> List[ChatOut]:
    rows = db.list_chats(limit=limit)
    return [_chat_to_out(r) for r in rows]


@app.post("/send", response_model=SendOut, dependencies=[Depends(verify_api_key)])
def post_send(item: SendIn) -> SendOut:
    item_id = db.enqueue_send(item.model_dump())
    with db.session_scope() as s:
        row = s.get(db.SendQueue, item_id)
        s.expunge(row)
        return _send_to_out(row)


@app.get("/send/next", response_model=Optional[SendOut], dependencies=[Depends(verify_api_key)])
def get_next_send() -> Optional[SendOut]:
    row = db.claim_next_send()
    if not row:
        return None
    return _send_to_out(row)


@app.post("/send/{item_id}/finish", response_model=OkOut, dependencies=[Depends(verify_api_key)])
def finish_send(item_id: int, ok: bool = True, error: Optional[str] = None) -> OkOut:
    db.finish_send(item_id, ok=ok, error=error)
    return OkOut(ok=True)


@app.get("/send/{item_id}", response_model=Optional[SendOut], dependencies=[Depends(verify_api_key)])
def get_send(item_id: int) -> Optional[SendOut]:
    with db.session_scope() as s:
        row = s.get(db.SendQueue, item_id)
        if not row:
            return None
        s.expunge(row)
        return _send_to_out(row)


@app.get("/status", response_model=StatusOut, dependencies=[Depends(verify_api_key)])
def get_status() -> StatusOut:
    return StatusOut(
        auth=db.get_auth_state(),
        queue=db.queue_stats(),
        undelivered=len(db.list_undelivered_events(limit=1000)),
        chats=len(db.list_chats(limit=1000)),
    )


# ---------- Auth state & 2FA ----------


class AuthStateIn(BaseModel):
    status: str
    error: Optional[str] = None


@app.post("/auth/state", response_model=OkOut, dependencies=[Depends(verify_api_key)])
def post_auth_state(body: AuthStateIn) -> OkOut:
    db.set_auth_state(body.status, error=body.error, last_login=body.status == "ok")
    return OkOut(ok=True)


class TwoFaRequestOut(BaseModel):
    request_id: int


@app.post("/auth/2fa/request", response_model=TwoFaRequestOut, dependencies=[Depends(verify_api_key)])
def post_2fa_request() -> TwoFaRequestOut:
    rid = db.open_2fa_request()
    return TwoFaRequestOut(request_id=rid)


class TwoFaCodeIn(BaseModel):
    request_id: int
    code: str


@app.post("/auth/2fa", response_model=OkOut, dependencies=[Depends(verify_api_key)])
def post_2fa(body: TwoFaCodeIn) -> OkOut:
    db.put_2fa_code(body.request_id, body.code)
    return OkOut(ok=True)


class TwoFaCodeOut(BaseModel):
    code: Optional[str] = None


@app.get("/auth/2fa/peek/{request_id}", response_model=TwoFaCodeOut, dependencies=[Depends(verify_api_key)])
def peek_2fa(request_id: int) -> TwoFaCodeOut:
    """Watcher опрашивает этот эндпоинт, чтобы забрать код, введённый владельцем."""

    code = db.take_pending_2fa_code(request_id)
    if code is not None:
        db.clear_2fa_request()
    return TwoFaCodeOut(code=code)


# ---------- Health-check для клиента MAX URL (для тестов ping) ----------


@app.get("/")
def root() -> dict:
    return {"service": "max-telegram-bridge-api", "version": "1.0.0"}


# ---------- Watcher headful-управление (прокси к watcher'у на 127.0.0.1:9000) ----------
# Это позволяет боту (и пользователю через noVNC) управлять браузером watcher'а
# в headful-режиме: ввод логина/пароля руками, прохождение капчи, 2FA и т.п.

import os
import aiohttp

WATCHER_HEADFUL_URL = os.getenv("WATCHER_HEADFUL_URL", "http://127.0.0.1:9000")


async def _proxy(method: str, path: str, json_body: dict | None = None, expect_binary: bool = False):
    url = WATCHER_HEADFUL_URL + path
    headers = {"X-Api-Key": os.getenv("BRIDGE_API_KEY", "")}
    timeout = aiohttp.ClientTimeout(total=120)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.request(method, url, json=json_body, headers=headers) as r:
                if expect_binary:
                    return r.status, await r.read(), r.headers.get("Content-Type", "image/png")
                text = await r.text()
                return r.status, text, r.headers.get("Content-Type", "application/json")
    except aiohttp.ClientError as exc:
        return 502, f"watcher unreachable: {exc}", "text/plain"


@app.get("/watcher/headful/state", dependencies=[Depends(verify_api_key)])
async def watcher_headful_state():
    status, body, _ = await _proxy("GET", "/state")
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=status, content=__import__("json").loads(body) if body and body.startswith("{") else {"raw": body})


@app.get("/watcher/headful/screenshot", dependencies=[Depends(verify_api_key)])
async def watcher_headful_screenshot():
    status, data, ctype = await _proxy("GET", "/screenshot", expect_binary=True)
    from fastapi.responses import Response
    return Response(status_code=status, content=data, media_type=ctype)


@app.post("/watcher/headful/enter", dependencies=[Depends(verify_api_key)])
async def watcher_headful_enter():
    status, body, _ = await _proxy("POST", "/enter")
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=status, content=__import__("json").loads(body) if body and body.startswith("{") else {"raw": body})


@app.post("/watcher/headful/exit", dependencies=[Depends(verify_api_key)])
async def watcher_headful_exit():
    status, body, _ = await _proxy("POST", "/exit")
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=status, content=__import__("json").loads(body) if body and body.startswith("{") else {"raw": body})


@app.post("/watcher/headful/click", dependencies=[Depends(verify_api_key)])
async def watcher_headful_click(payload: dict):
    status, body, _ = await _proxy("POST", "/click", json_body=payload)
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=status, content=__import__("json").loads(body) if body and body.startswith("{") else {"raw": body})


@app.post("/watcher/headful/type", dependencies=[Depends(verify_api_key)])
async def watcher_headful_type(payload: dict):
    status, body, _ = await _proxy("POST", "/type", json_body=payload)
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=status, content=__import__("json").loads(body) if body and body.startswith("{") else {"raw": body})


@app.post("/watcher/headful/key", dependencies=[Depends(verify_api_key)])
async def watcher_headful_key(payload: dict):
    status, body, _ = await _proxy("POST", "/key", json_body=payload)
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=status, content=__import__("json").loads(body) if body and body.startswith("{") else {"raw": body})


@app.post("/watcher/headful/fill", dependencies=[Depends(verify_api_key)])
async def watcher_headful_fill(payload: dict):
    status, body, _ = await _proxy("POST", "/fill", json_body=payload)
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=status, content=__import__("json").loads(body) if body and body.startswith("{") else {"raw": body})


@app.post("/watcher/headful/wait", dependencies=[Depends(verify_api_key)])
async def watcher_headful_wait(payload: dict):
    status, body, _ = await _proxy("POST", "/wait", json_body=payload)
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=status, content=__import__("json").loads(body) if body and body.startswith("{") else {"raw": body})


@app.post("/watcher/headful/evaluate", dependencies=[Depends(verify_api_key)])
async def watcher_headful_evaluate(payload: dict):
    status, body, _ = await _proxy("POST", "/evaluate", json_body=payload)
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=status, content=__import__("json").loads(body) if body and body.startswith("{") else {"raw": body})


@app.post("/watcher/headful/navigate", dependencies=[Depends(verify_api_key)])
async def watcher_headful_navigate(payload: dict):
    status, body, _ = await _proxy("POST", "/navigate", json_body=payload)
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=status, content=__import__("json").loads(body) if body and body.startswith("{") else {"raw": body})


@app.post("/watcher/headful/reload", dependencies=[Depends(verify_api_key)])
async def watcher_headful_reload():
    status, body, _ = await _proxy("POST", "/reload")
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=status, content=__import__("json").loads(body) if body and body.startswith("{") else {"raw": body})


@app.post("/watcher/headful/scroll", dependencies=[Depends(verify_api_key)])
async def watcher_headful_scroll(payload: dict):
    status, body, _ = await _proxy("POST", "/scroll", json_body=payload)
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=status, content=__import__("json").loads(body) if body and body.startswith("{") else {"raw": body})


@app.post("/watcher/headful/cookies", dependencies=[Depends(verify_api_key)])
async def watcher_headful_cookies(payload: dict):
    status, body, _ = await _proxy("POST", "/cookies", json_body=payload)
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=status, content=__import__("json").loads(body) if body and body.startswith("{") else {"raw": body})

# ---------- noVNC-прокси (чтобы вся VNC-сессия шла через :8000) ----------
# Внутри supervisord novnc висит на 5900/6080. Здесь мы проксируем
# /vnc/* (статику noVNC) и /vnc/websockify (WebSocket) на 127.0.0.1:6080,
# чтобы Railway проксировал только :8000 (а :6080 не публичный).

NOVNC_UPSTREAM_HTTP = "http://127.0.0.1:6080"
NOVNC_UPSTREAM_WS = "ws://127.0.0.1:6080"
VNC_PUBLIC = os.getenv("VNC_PUBLIC", "1") == "1"


@app.get("/vnc", include_in_schema=False)
async def vnc_redirect():
    """Главная noVNC-страница: редирект на vnc.html с автоконнектом.

    Пароль VNC НЕ передаётся в URL — он остаётся на стороне сервера.
    Если пароль всё-таки задан в ENV, мы передаём его через хэш-параметр,
    который noVNC интерпретирует как «prefilled password» (не сохраняется в referrer).
    """
    if not VNC_PUBLIC:
        return Response(status_code=404, content=b"vnc disabled")
    from fastapi.responses import RedirectResponse
    pwd = os.getenv("VNC_PASSWORD", "")
    # noVNC принимает password через query-параметр, но Railway и браузеры логируют Referer.
    # Чтобы не утекал — кладём пароль в хэш (фрагмент), который не отправляется на сервер.
    target = "/vnc/vnc.html?autoconnect=true&resize=scale&path=vnc/websockify"
    if pwd:
        target += f"#password={pwd}"
    return RedirectResponse(url=target, status_code=302)


@app.websocket("/vnc/websockify")
async def novnc_websocket(websocket):
    """Проксирование WebSocket-соединения noVNC к локальному websockify (:6080).

    aiohttp.ClientSession.request() не умеет апгрейдить HTTP→WebSocket,
    поэтому используем явный ws_connect() и зеркалим байты между
    клиентом (noVNC в браузере) и апстримом (websockify → x11vnc).
    """
    import asyncio
    if not VNC_PUBLIC:
        await websocket.close(code=1008, reason="vnc disabled")
        return

    upstream_url = NOVNC_UPSTREAM_WS + "/websockify"
    client_session = aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=None, connect=10, sock_connect=10, sock_read=None)
    )
    upstream: aiohttp.ClientWebSocketResponse | None = None
    try:
        upstream = await client_session.ws_connect(upstream_url, autoclose=False, autoping=False)
    except Exception as exc:
        try:
            await websocket.close(code=1011, reason=f"upstream connect failed: {exc}")
        finally:
            await client_session.close()
        return

    async def _client_to_upstream():
        try:
            while True:
                msg = await websocket.receive()
                if msg is None:
                    break
                mtype = msg.get("type")
                if mtype == "websocket.receive":
                    if "text" in msg and msg["text"] is not None:
                        await upstream.send_str(msg["text"])
                    elif "bytes" in msg and msg["bytes"] is not None:
                        await upstream.send_bytes(msg["bytes"])
                elif mtype == "websocket.disconnect":
                    break
        except Exception:
            pass
        finally:
            try:
                await upstream.close(code=1000)
            except Exception:
                pass

    async def _upstream_to_client():
        try:
            async for msg in upstream:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await websocket.send_text(msg.data)
                elif msg.type == aiohttp.WSMsgType.BINARY:
                    await websocket.send_bytes(msg.data)
                elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    break
        except Exception:
            pass
        finally:
            try:
                await websocket.close()
            except Exception:
                pass

    try:
        await asyncio.gather(_client_to_upstream(), _upstream_to_client())
    finally:
        try:
            if upstream is not None and not upstream.closed:
                await upstream.close()
        except Exception:
            pass
        await client_session.close()


@app.api_route("/vnc/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"], include_in_schema=False)
async def novnc_proxy(full_path: str, request: Request):
    if not VNC_PUBLIC:
        return Response(status_code=404, content=b"vnc disabled")
    target = f"{NOVNC_UPSTREAM_HTTP}/{full_path}"
    if request.url.query:
        target += f"?{request.url.query}"
    headers = {k: v for k, v in request.headers.items() if k.lower() not in {"host", "x-api-key"}}
    body = await request.body()
    timeout = aiohttp.ClientTimeout(total=300)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.request(request.method, target, data=body, headers=headers) as r:
            content = await r.read()
            return Response(
                content=content,
                status_code=r.status,
                media_type=r.headers.get("Content-Type", "application/octet-stream"),
                headers={k: v for k, v in r.headers.items() if k.lower() not in {"transfer-encoding", "content-encoding", "content-length"}},
            )
