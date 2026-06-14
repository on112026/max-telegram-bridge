"""Хэндлеры команд и callback'ов Telegram-бота."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from app.api_client import api
from app.config import settings
from app.keyboards import event_inline_keyboard, main_reply_keyboard
from app.sender import forward_event
from app.states import ReplyState

logger = logging.getLogger(__name__)

MAX_TG_DOWNLOAD = 49 * 1024 * 1024


def _is_allowed(user_id: int) -> bool:
    if not settings.allowed_tg_user_ids:
        return False
    return user_id in settings.allowed_tg_user_ids


async def _reject(message: types.Message) -> None:
    await message.answer("⛔ Бот принимает сообщения только от авторизованных пользователей.")


def _escape(text: str) -> str:
    return (text or "").replace("&", "&").replace("<", "<").replace(">", ">")


def _format_chat(chat: Dict[str, Any]) -> str:
    title = chat.get("title") or "—"
    cid = chat.get("max_chat_id")
    last = chat.get("last_message_preview") or ""
    return f"<b>{_escape(title)}</b>\nID: <code>{cid}</code>\n{_escape(last[:120])}"


# ---------- Команды ----------


async def start_command(message: types.Message) -> None:
    if not _is_allowed(message.from_user.id):
        return await _reject(message)
    await message.answer(
        "👋 Я мост MAX → Telegram.\n"
        "Все новые сообщения MAX будут приходить сюда автоматически.\n"
        "Ответить — кнопка «💬 Ответить» под сообщением или /reply <chat_id>.",
        reply_markup=main_reply_keyboard(),
    )


async def help_command(message: types.Message) -> None:
    if not _is_allowed(message.from_user.id):
        return await _reject(message)
    await message.answer(
        "Команды:\n"
        "/start, /help — подсказка\n"
        "/status — состояние моста\n"
        "/chats — список MAX-чатов\n"
        "/reply <chat_id> — следующее сообщение уйдёт в этот чат\n"
        "/history <chat_id> [N=20] — последние N сообщений\n"
        "/reauth — инструкция по повторной авторизации\n"
        "/cancel — выйти из режима ответа\n",
        reply_markup=main_reply_keyboard(),
    )


async def status_command(message: types.Message) -> None:
    if not _is_allowed(message.from_user.id):
        return await _reject(message)
    try:
        s = await api.status()
    except Exception as exc:
        await message.answer(f"⚠️ Не удалось получить статус API: {exc}")
        return
    auth = s.get("auth", {})
    queue = s.get("queue", {})
    text = (
        f"🔐 MAX auth: <b>{_escape(str(auth.get('status')))}</b>\n"
        f"   last_login: {auth.get('last_login_at') or '—'}\n"
        f"   error: {_escape(str(auth.get('last_error') or '—'))}\n"
        f"📬 Недоставлено: <b>{s.get('undelivered')}</b>\n"
        f"💬 Чатов в кэше: <b>{s.get('chats')}</b>\n"
        f"📤 Очередь отправки: pending={queue.get('pending')} "
        f"in_progress={queue.get('in_progress')} sent={queue.get('sent')} failed={queue.get('failed')}"
    )
    await message.answer(text, parse_mode="HTML")


async def chats_command(message: types.Message) -> None:
    if not _is_allowed(message.from_user.id):
        return await _reject(message)
    try:
        chats = await api.list_chats()
    except Exception as exc:
        await message.answer(f"⚠️ Не удалось получить список чатов: {exc}")
        return
    if not chats:
        await message.answer("Пока нет ни одного чата. Откройте какой-нибудь чат в MAX Web.")
        return
    for c in chats[:30]:
        await message.answer(_format_chat(c), parse_mode="HTML")


async def history_command(message: types.Message) -> None:
    if not _is_allowed(message.from_user.id):
        return await _reject(message)
    args = (message.text or "").split()
    if len(args) < 2:
        await message.answer("Использование: /history <chat_id> [N=20]")
        return
    chat_id = args[1]
    limit = 20
    if len(args) >= 3:
        try:
            limit = max(1, min(int(args[2]), 100))
        except ValueError:
            limit = 20
    try:
        events = await api.list_events_for_chat(chat_id, limit=limit)
    except Exception as exc:
        await message.answer(f"⚠️ Ошибка: {exc}")
        return
    if not events:
        await message.answer("История пуста.")
        return
    for ev in events:
        try:
            await forward_event(message.bot, message.chat.id, ev)
            await message.answer(
                "—", reply_markup=event_inline_keyboard(ev.get("id", 0), ev.get("max_chat_id", ""))
            )
        except Exception as exc:
            await message.answer(f"⚠️ Не удалось переслать {ev.get('id')}: {exc}")


async def reauth_command(message: types.Message) -> None:
    if not _is_allowed(message.from_user.id):
        return await _reject(message)
    try:
        await api.status()
    except Exception as exc:
        await message.answer(f"⚠️ API недоступен: {exc}")
        return
    await message.answer(
        "🔁 Запустите на сервере:\n"
        "<code>cd max-telegram-bridge && make reauth</code>\n"
        "После ручного входа в MAX выполните:\n<code>make restart-watcher</code>",
        parse_mode="HTML",
    )


async def cancel_command(message: types.Message, state: FSMContext) -> None:
    if not _is_allowed(message.from_user.id):
        return await _reject(message)
    await state.clear()
    await message.answer("Ок, вышел из режима ответа.")


# ---------- Reply keyboard buttons ----------


async def button_status(message: types.Message) -> None:
    await status_command(message)


async def button_chats(message: types.Message) -> None:
    await chats_command(message)


async def button_help(message: types.Message) -> None:
    await help_command(message)


async def button_listen(message: types.Message) -> None:
    """Кнопка «Слушать MAX» — повторный опрос текущего состояния/чатов."""

    if not _is_allowed(message.from_user.id):
        return await _reject(message)
    try:
        s = await api.status()
        auth = s.get("auth", {}).get("status", "unknown")
        undelivered = s.get("undelivered", 0)
    except Exception as exc:
        await message.answer(f"⚠️ API: {exc}")
        return
    await message.answer(
        f"🔄 MAX-сессия: <b>{_escape(str(auth))}</b>\n"
        f"📬 Недоставленных событий: <b>{undelivered}</b>\n"
        f"Слушаю автоматически. Команда /chats — список диалогов.",
        parse_mode="HTML",
    )


# ---------- Reply FSM ----------


async def reply_command(message: types.Message, state: FSMContext) -> None:
    if not _is_allowed(message.from_user.id):
        return await _reject(message)
    args = (message.text or "").split()
    if len(args) < 2:
        await message.answer("Использование: /reply <chat_id>")
        return
    await state.set_state(ReplyState.waiting_text)
    await state.update_data(target_chat_id=args[1])
    await message.answer(
        f"✍️ Введите сообщение для чата <code>{_escape(args[1])}</code>.\n"
        "Можно отправить фото/видео/документ/голос/кружочек — всё уйдёт туда.\n"
        "/cancel — выйти.",
        parse_mode="HTML",
    )


async def reply_text(message: types.Message, state: FSMContext) -> None:
    if not _is_allowed(message.from_user.id):
        return await _reject(message)
    data = await state.get_data()
    target = data.get("target_chat_id")
    if not target:
        await state.clear()
        return
    text = message.text or ""
    try:
        res = await api.enqueue_send(
            target_chat_id=target, kind="text", text=text, created_by=message.from_user.id
        )
        await message.answer(
            f"✅ Отправлено в очередь (id={res.get('id')}). Дождитесь подтверждения от MAX."
        )
    except Exception as exc:
        await message.answer(f"⚠️ Ошибка постановки в очередь: {exc}")
    await state.clear()


async def reply_media(message: types.Message, state: FSMContext) -> None:
    if not _is_allowed(message.from_user.id):
        return await _reject(message)
    data = await state.get_data()
    target = data.get("target_chat_id")
    if not target:
        await state.clear()
        return

    kind = "document"
    file_id = None
    caption = message.caption or ""
    if message.photo:
        kind = "photo"
        file_id = message.photo[-1].file_id
    elif message.video:
        kind = "video"
        file_id = message.video.file_id
    elif message.video_note:
        kind = "video_note"
        file_id = message.video_note.file_id
    elif message.voice:
        kind = "voice"
        file_id = message.voice.file_id
    elif message.audio:
        kind = "audio"
        file_id = message.audio.file_id
    elif message.document:
        kind = "document"
        file_id = message.document.file_id
    else:
        await message.answer("Пришлите текст, фото, видео, голос, кружочек или документ.")
        return

    if not file_id:
        await message.answer("Не удалось получить файл.")
        return

    try:
        tg_file = await message.bot.get_file(file_id)
        if tg_file.file_size and tg_file.file_size > MAX_TG_DOWNLOAD:
            await message.answer("Файл больше 50 МБ — Telegram не отдаёт его боту.")
            return
        os.makedirs(os.path.join(settings.media_dir, "outbox"), exist_ok=True)
        local_name = f"{tg_file.file_unique_id}_{os.path.basename(tg_file.file_path or 'file')}"
        local_path = os.path.join(settings.media_dir, "outbox", local_name)
        await message.bot.download_file(tg_file.file_path, local_path)
        rel = os.path.relpath(local_path, settings.media_dir)
        res = await api.enqueue_send(
            target_chat_id=target,
            kind=kind,
            text=caption,
            media_path=rel,
            media_mime=message.content_type,
            media_filename=local_name,
            created_by=message.from_user.id,
        )
        await message.answer(
            f"📨 Медиа поставлено в очередь (id={res.get('id')}, {kind}). "
            "Дождитесь подтверждения от MAX."
        )
    except Exception as exc:
        await message.answer(f"⚠️ Ошибка: {exc}")
    await state.clear()


# ---------- Inline callbacks ----------


async def reply_callback(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not _is_allowed(callback.from_user.id):
        return await callback.answer("⛔", show_alert=True)
    if not callback.data or ":" not in callback.data:
        return await callback.answer()
    _, chat_id = callback.data.split(":", 1)
    await state.set_state(ReplyState.waiting_text)
    await state.update_data(target_chat_id=chat_id)
    await callback.answer()
    await callback.message.answer(
        f"✍️ Введите сообщение для чата <code>{_escape(chat_id)}</code> "
        "(или пришлите фото/видео/голос/кружочек/документ).\n/cancel — выйти.",
        parse_mode="HTML",
    )


async def showid_callback(callback: types.CallbackQuery) -> None:
    if not callback.data or ":" not in callback.data:
        return await callback.answer()
    _, chat_id = callback.data.split(":", 1)
    await callback.answer(f"ID: {chat_id}", show_alert=True)


async def history_callback(callback: types.CallbackQuery) -> None:
    if not callback.from_user or not _is_allowed(callback.from_user.id):
        return await callback.answer("⛔", show_alert=True)
    if not callback.data or ":" not in callback.data:
        return await callback.answer()
    _, chat_id = callback.data.split(":", 1)
    await callback.answer()
    try:
        events = await api.list_events_for_chat(chat_id, limit=20)
    except Exception as exc:
        await callback.message.answer(f"⚠️ Ошибка: {exc}")
        return
    if not events:
        await callback.message.answer("История пуста.")
        return
    for ev in events:
        try:
            await forward_event(callback.message.bot, callback.message.chat.id, ev)
        except Exception as exc:
            await callback.message.answer(f"⚠️ Не удалось переслать {ev.get('id')}: {exc}")


# ---------- Регистрация ----------


def register_handlers(dp: Dispatcher) -> None:
    dp.message.register(start_command, Command("start"))
    dp.message.register(help_command, Command("help"))
    dp.message.register(status_command, Command("status"))
    dp.message.register(chats_command, Command("chats"))
    dp.message.register(history_command, Command("history"))
    dp.message.register(reauth_command, Command("reauth"))
    dp.message.register(reply_command, Command("reply"))
    dp.message.register(cancel_command, Command("cancel"))

    dp.message.register(button_status, F.text == "ℹ️ Статус")
    dp.message.register(button_chats, F.text == "📚 Чаты")
    dp.message.register(button_help, F.text == "🆘 Помощь")
    dp.message.register(button_listen, F.text == "📥 Слушать MAX")

    dp.message.register(
        reply_text, ReplyState.waiting_text, F.content_type == "text"
    )
    dp.message.register(
        reply_media,
        ReplyState.waiting_text,
        F.content_type.in_({"photo", "video", "video_note", "voice", "audio", "document"}),
    )

    dp.callback_query.register(reply_callback, F.callback_data.startswith("reply:"))
    dp.callback_query.register(showid_callback, F.callback_data.startswith("showid:"))
    dp.callback_query.register(history_callback, F.callback_data.startswith("history:"))