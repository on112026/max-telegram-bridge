"""Клавиатуры Telegram-бота."""

from __future__ import annotations

from typing import Any, Dict, List

from aiogram import types


def main_reply_keyboard() -> types.ReplyKeyboardMarkup:
    return types.ReplyKeyboardMarkup(
        keyboard=[
            [types.KeyboardButton(text="📥 Слушать MAX")],
            [types.KeyboardButton(text="📚 Чаты"), types.KeyboardButton(text="ℹ️ Статус")],
            [types.KeyboardButton(text="🆘 Помощь"), types.KeyboardButton(text="🔐 /reauth")],
        ],
        resize_keyboard=True,
        selective=True,
    )


def event_inline_keyboard(event_id: int, max_chat_id: str) -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="💬 Ответить", callback_data=f"reply:{max_chat_id}"
                ),
                types.InlineKeyboardButton(
                    text="📋 ID чата", callback_data=f"showid:{max_chat_id}"
                ),
            ],
            [
                types.InlineKeyboardButton(
                    text="🔄 История", callback_data=f"history:{max_chat_id}"
                ),
            ],
        ]
    )


# ----------------------------------------------------------------------
# Headful-режим: клавиатура для ручного управления MAX через бота
# ----------------------------------------------------------------------


def headful_main_keyboard() -> types.InlineKeyboardMarkup:
    """Главная панель действий в headful-режиме."""
    return types.InlineKeyboardMarkup(
        inline_keyboard=[
            [
                types.InlineKeyboardButton(
                    text="📸 Скриншот", callback_data="hf:shot"
                ),
                types.InlineKeyboardButton(
                    text="🔄 Обновить", callback_data="hf:reload"
                ),
            ],
            [
                types.InlineKeyboardButton(
                    text="⌨️ Печатать", callback_data="hf:type"
                ),
                types.InlineKeyboardButton(
                    text="⏎ Enter", callback_data="hf:key:Enter"
                ),
                types.InlineKeyboardButton(
                    text="⎋ Esc", callback_data="hf:key:Escape"
                ),
            ],
            [
                types.InlineKeyboardButton(
                    text="🔍 Заполнить поле", callback_data="hf:fill"
                ),
                types.InlineKeyboardButton(
                    text="🖱 Кликнуть", callback_data="hf:click"
                ),
            ],
            [
                types.InlineKeyboardButton(
                    text="⏳ Ждать элемент", callback_data="hf:wait"
                ),
                types.InlineKeyboardButton(
                    text="🌐 Открыть URL", callback_data="hf:nav"
                ),
            ],
            [
                types.InlineKeyboardButton(
                    text="⬇️ Прокрутить", callback_data="hf:scroll"
                ),
                types.InlineKeyboardButton(
                    text="⬆️", callback_data="hf:scrollup"
                ),
            ],
            [
                types.InlineKeyboardButton(
                    text="🧹 Очистить cookies", callback_data="hf:clear"
                ),
            ],
            [
                types.InlineKeyboardButton(
                    text="✅ Готово (выйти)", callback_data="hf:done"
                ),
                types.InlineKeyboardButton(
                    text="❌ Отмена", callback_data="hf:cancel"
                ),
            ],
        ]
    )