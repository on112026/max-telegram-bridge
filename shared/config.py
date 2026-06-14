"""Общая загрузка конфигурации из окружения."""

from __future__ import annotations

import os
import logging
import secrets
from dataclasses import dataclass, field
from typing import List, Optional


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    val = os.getenv(name)
    if val is None or val == "":
        return default
    return val


def _env_int(name: str, default: int) -> int:
    val = _env(name)
    if val is None:
        return default
    try:
        return int(val)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    val = _env(name)
    if val is None:
        return default
    try:
        return float(val)
    except ValueError:
        return default


def _env_list(name: str, default: List[str] | None = None) -> List[str]:
    val = _env(name)
    if not val:
        return list(default or [])
    return [item.strip() for item in val.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    # Telegram
    telegram_bot_token: str = ""
    allowed_tg_user_ids: List[int] = field(default_factory=list)

    # MAX
    max_phone: str = ""
    max_password: str = ""
    max_totp_secret: str = ""
    max_web_url: str = "https://web.max.ru"

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    db_path: str = "/data/bridge.db"
    media_dir: str = "/data/media"
    profile_dir: str = "/data/max-profile"
    bridge_api_key: str = ""

    # Watcher
    watcher_poll_interval: float = 1.5
    watcher_health_interval: int = 30
    watcher_history_backfill: int = 50

    # Misc
    log_level: str = "INFO"


def load_settings() -> Settings:
    """Загружает настройки и применяет безопасные дефолты."""

    api_key = _env("BRIDGE_API_KEY") or secrets.token_urlsafe(32)
    if not _env("BRIDGE_API_KEY"):
        logging.getLogger(__name__).warning(
            "BRIDGE_API_KEY не задан в .env — сгенерирован одноразовый ключ для текущего запуска."
        )

    return Settings(
        telegram_bot_token=_env("TELEGRAM_BOT_TOKEN", "") or "",
        allowed_tg_user_ids=[
            int(x) for x in _env_list("ALLOWED_TG_USER_IDS") if x.isdigit()
        ],
        max_phone=_env("MAX_PHONE", "") or "",
        max_password=_env("MAX_PASSWORD", "") or "",
        max_totp_secret=_env("MAX_TOTP_SECRET", "") or "",
        max_web_url=_env("MAX_WEB_URL", "https://web.max.ru") or "https://web.max.ru",
        api_host=_env("API_HOST", "0.0.0.0") or "0.0.0.0",
        api_port=_env_int("API_PORT", 8000),
        db_path=_env("DB_PATH", "/data/bridge.db") or "/data/bridge.db",
        media_dir=_env("MEDIA_DIR", "/data/media") or "/data/media",
        profile_dir=_env("PROFILE_DIR", "/data/max-profile") or "/data/max-profile",
        bridge_api_key=api_key,
        watcher_poll_interval=_env_float("WATCHER_POLL_INTERVAL", 1.5),
        watcher_health_interval=_env_int("WATCHER_HEALTH_INTERVAL", 30),
        watcher_history_backfill=_env_int("WATCHER_HISTORY_BACKFILL", 50),
        log_level=_env("LOG_LEVEL", "INFO") or "INFO",
    )