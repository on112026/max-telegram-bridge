"""Единая настройка логирования с маскированием секретов."""

from __future__ import annotations

import logging
import re

_SECRETS = ("BRIDGE_API_KEY", "TELEGRAM_BOT_TOKEN", "MAX_PASSWORD", "MAX_TOTP_SECRET")

_MASK_PATTERNS = [
    re.compile(r"(BRIDGE_API_KEY=)[^\s\r\n]+"),
    re.compile(r"(TELEGRAM_BOT_TOKEN=)[^\s\r\n]+"),
    re.compile(r"(MAX_PASSWORD=)[^\s\r\n]+"),
    re.compile(r"(MAX_TOTP_SECRET=)[^\s\r\n]+"),
    re.compile(r"(?i)(bot)(\d{4,})(:)(\S{6,})"),  # токен TG
]


class SecretsFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
        try:
            msg = record.getMessage()
        except Exception:
            return True
        for pat in _MASK_PATTERNS:
            msg = pat.sub(lambda m: m.group(1) + "***" if m.lastindex and m.lastindex >= 2 else "***", msg)
        record.msg = msg
        record.args = ()
        return True


def configure_logging(level: str = "INFO") -> None:
    """Настраивает корневой логгер с маскированием."""

    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
    )
    handler.addFilter(SecretsFilter())
    root.addHandler(handler)
    try:
        root.setLevel(getattr(logging, level.upper()))
    except AttributeError:
        root.setLevel(logging.INFO)
    # Приглушаем очень шумные библиотеки
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("playwright").setLevel(logging.WARNING)