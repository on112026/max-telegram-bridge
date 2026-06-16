"""FSM-состояния Telegram-бота."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class ReplyState(StatesGroup):
    waiting_text = State()
    waiting_media = State()


class HeadfulState(StatesGroup):
    """Состояния FSM для ручного управления MAX-сессией через бота."""

    # В режиме headful пользователь видит скриншоты и нажимает inline-кнопки.
    # Когда он нажал «⌨️ Печатать» / «🔍 Заполнить поле», мы ждём,
    # что он пришлёт обычное текстовое сообщение.
    waiting_type_text = State()
    waiting_fill_selector = State()
    waiting_fill_value = State()
    waiting_key = State()
    waiting_wait_selector = State()
    waiting_navigate_url = State()