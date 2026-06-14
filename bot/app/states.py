"""FSM-состояния Telegram-бота."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class ReplyState(StatesGroup):
    waiting_text = State()
    waiting_media = State()