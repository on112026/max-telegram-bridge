"""Скачивание медиа из MAX по прямой ссылке (или из data: URL)."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import httpx
from playwright.async_api import Page

from app.config import settings

logger = logging.getLogger(__name__)


_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_filename(name: str) -> str:
    name = name.strip().replace(" ", "_")
    name = _SAFE_NAME.sub("_", name) or "file"
    return name[:120]


async def download_url_to_media(url: str, suggested_name: Optional[str] = None) -> Optional[dict]:
    """Скачивает файл по URL в MEDIA_DIR/inbox. Возвращает метаданные или None."""

    os.makedirs(os.path.join(settings.media_dir, "inbox"), exist_ok=True)
    filename = _safe_filename(suggested_name or os.path.basename(urlparse(url).path) or "file")
    target = Path(settings.media_dir) / "inbox" / filename
    try:
        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as c:
            async with c.stream("GET", url) as r:
                r.raise_for_status()
                mime = r.headers.get("content-type")
                with open(target, "wb") as f:
                    async for chunk in r.aiter_bytes(64 * 1024):
                        f.write(chunk)
                size = target.stat().st_size
        rel = os.path.relpath(target, settings.media_dir)
        return {
            "media_path": rel,
            "media_mime": mime,
            "media_filename": filename,
            "media_size": size,
        }
    except Exception as exc:  # pragma: no cover
        logger.warning("download_url_to_media failed: %s", exc)
        return None


async def download_via_browser(page: Page, url: str, suggested_name: Optional[str] = None) -> Optional[dict]:
    """Резервный способ — скачиваем файлом через CDP (Page.download) не применимо к MAX,
    но иногда удобно через fetch в контексте страницы, чтобы не потерять cookies."""

    os.makedirs(os.path.join(settings.media_dir, "inbox"), exist_ok=True)
    filename = _safe_filename(suggested_name or "file")
    target = Path(settings.media_dir) / "inbox" / filename
    try:
        data_b64 = await page.evaluate(
            """async (url) => {
                try {
                    const r = await fetch(url, { credentials: 'include' });
                    if (!r.ok) return null;
                    const buf = await r.arrayBuffer();
                    let bin = '';
                    const bytes = new Uint8Array(buf);
                    const len = bytes.byteLength;
                    const chunk = 0x8000;
                    for (let i = 0; i < len; i += chunk) {
                        bin += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
                    }
                    return btoa(bin);
                } catch (e) { return null; }
            }""",
            url,
        )
        if not data_b64:
            return None
        import base64

        data = base64.b64decode(data_b64)
        with open(target, "wb") as f:
            f.write(data)
        return {
            "media_path": os.path.relpath(target, settings.media_dir),
            "media_filename": filename,
            "media_size": target.stat().st_size,
        }
    except Exception as exc:  # pragma: no cover
        logger.warning("download_via_browser failed: %s", exc)
        return None