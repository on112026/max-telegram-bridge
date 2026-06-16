"""HTTP-сервер, который слушает команды headful-управления от api.

Стартует как asyncio-задача в run.py параллельно с основным циклом.
Использует aiohttp, который уже подтягивается aiogram.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from aiohttp import web

from app.config import settings
from app.loop import get_supervisor

logger = logging.getLogger(__name__)


async def _state(req: web.Request) -> web.Response:
    sup = get_supervisor()
    return web.json_response(await sup.headful.state())


async def _screenshot(req: web.Request) -> web.Response:
    sup = get_supervisor()
    png = await sup.headful.screenshot()
    return web.Response(body=png, content_type="image/png")


async def _enter_headful(req: web.Request) -> web.Response:
    sup = get_supervisor()
    res = await sup.enter_headful()
    return web.json_response(res)


async def _exit_headful(req: web.Request) -> web.Response:
    sup = get_supervisor()
    res = await sup.exit_headful()
    return web.json_response(res)


async def _click(req: web.Request) -> web.Response:
    data = await req.json()
    sup = get_supervisor()
    await sup.headful.click(int(data["x"]), int(data["y"]), data.get("button", "left"))
    return web.json_response({"ok": True})


async def _type(req: web.Request) -> web.Response:
    data = await req.json()
    sup = get_supervisor()
    await sup.headful.type_text(data["text"], float(data.get("delay", 0)))
    return web.json_response({"ok": True})


async def _key(req: web.Request) -> web.Response:
    data = await req.json()
    sup = get_supervisor()
    await sup.headful.press_key(data["key"])
    return web.json_response({"ok": True})


async def _fill(req: web.Request) -> web.Response:
    data = await req.json()
    sup = get_supervisor()
    await sup.headful.fill(data["selector"], data["value"])
    return web.json_response({"ok": True})


async def _wait(req: web.Request) -> web.Response:
    data = await req.json()
    sup = get_supervisor()
    ok = await sup.headful.wait_selector(data["selector"], float(data.get("timeout", 10)))
    return web.json_response({"ok": ok})


async def _evaluate(req: web.Request) -> web.Response:
    data = await req.json()
    sup = get_supervisor()
    res: Any = await sup.headful.evaluate(data["script"])
    return web.json_response({"ok": True, "result": res})


async def _navigate(req: web.Request) -> web.Response:
    data = await req.json()
    sup = get_supervisor()
    await sup.headful.navigate(data["url"])
    return web.json_response({"ok": True})


async def _reload(req: web.Request) -> web.Response:
    sup = get_supervisor()
    await sup.headful.reload()
    return web.json_response({"ok": True})


async def _back(req: web.Request) -> web.Response:
    sup = get_supervisor()
    await sup.headful.back()
    return web.json_response({"ok": True})


async def _forward(req: web.Request) -> web.Response:
    sup = get_supervisor()
    await sup.headful.forward()
    return web.json_response({"ok": True})


async def _scroll(req: web.Request) -> web.Response:
    data = await req.json()
    sup = get_supervisor()
    await sup.headful.scroll(int(data.get("delta_y", 300)))
    return web.json_response({"ok": True})


async def _cookies(req: web.Request) -> web.Response:
    sup = get_supervisor()
    action = (await req.json()).get("action", "get")
    if action == "clear":
        await sup.headful.clear_cookies()
        return web.json_response({"ok": True, "action": "cleared"})
    return web.json_response(await sup.headful.cookies())


async def _health(req: web.Request) -> web.Response:
    return web.json_response({"ok": True, "service": "watcher-headful"})


async def _check_api_key(request: web.Request) -> None:
    expected = settings.bridge_api_key
    if not expected:
        raise web.HTTPServiceUnavailable(reason="API key not configured")
    got = request.headers.get("X-Api-Key", "")
    if got != expected:
        raise web.HTTPUnauthorized(reason="Invalid API key")


def build_app() -> web.Application:
    app = web.Application()
    # Middleware-like check — обернём вручную
    async def guarded(req: web.Request) -> web.StreamResponse | None:
        if req.path == "/health":
            return None
        await _check_api_key(req)
        return None

    @web.middleware
    async def auth_mw(request: web.Request, handler):
        if request.path != "/health":
            await _check_api_key(request)
        return await handler(request)

    app.middlewares.append(auth_mw)

    app.router.add_get("/health", _health)
    app.router.add_get("/state", _state)
    app.router.add_get("/screenshot", _screenshot)
    app.router.add_post("/enter", _enter_headful)
    app.router.add_post("/exit", _exit_headful)
    app.router.add_post("/click", _click)
    app.router.add_post("/type", _type)
    app.router.add_post("/key", _key)
    app.router.add_post("/fill", _fill)
    app.router.add_post("/wait", _wait)
    app.router.add_post("/evaluate", _evaluate)
    app.router.add_post("/navigate", _navigate)
    app.router.add_post("/reload", _reload)
    app.router.add_post("/back", _back)
    app.router.add_post("/forward", _forward)
    app.router.add_post("/scroll", _scroll)
    app.router.add_post("/cookies", _cookies)
    return app


async def run_headful_server(host: str = "127.0.0.1", port: int = 9000) -> None:
    app = build_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    logger.info("Headful control server listening on http://%s:%s", host, port)
    # Держим сервер живым
    while True:
        await asyncio.sleep(3600)