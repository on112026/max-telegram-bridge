"""Хэндлеры команд и callback'ов Telegram-бота."""

from __future__ import annotations

import io
import logging
import os
from typing import Any, Dict, List

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from app.api_client import api
from app.config import settings
from app.keyboards import event_inline_keyboard, headful_main_keyboard, main_reply_keyboard
from app.sender import forward_event
from app.states import HeadfulState, ReplyState

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
        "Ответить — кнопка «💬 Ответить» под сообщением или /reply <chat_id>.\n"
        "Если MAX-сессия слетела — /reauth: я покажу экран MAX в Telegram.",
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
        "/reauth — открыть управляемый экран MAX (бот пришлёт скриншоты)\n"
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


# ---------- /reauth — управляемый экран MAX ----------


async def reauth_command(message: types.Message, state: FSMContext) -> None:
    """Запустить headful-режим: переключить watcher на headful chromium,
    прислать первый скриншот и показать inline-клавиатуру.
    """
    if not _is_allowed(message.from_user.id):
        return await _reject(message)

    await message.answer("🖥 Открываю MAX в управляемом режиме…")
    try:
        await api.headful_enter()
    except Exception as exc:
        await message.answer(
            f"⚠️ Не удалось перевести watcher в headful-режим: {exc}\n"
            "Возможно, watcher уже в headful-режиме или не отвечает."
        )
        return

    await state.set_state(HeadfulState.waiting_type_text)  # базовое FSM-состояние headful
    await state.update_data(chat_id=message.chat.id)

    try:
        png = await api.headful_screenshot()
        await message.bot.send_photo(
            chat_id=message.chat.id,
            photo=types.BufferedInputFile(png, filename="max.png"),
            caption=(
                "📺 Экран MAX. Управляйте кнопками ниже.\n"
                "Если у вас есть VNC-доступ, можно открыть то же окно в браузере: "
                "/vnc."
            ),
            reply_markup=headful_main_keyboard(),
        )
    except Exception as exc:
        await message.answer(
            f"⚠️ Headful-режим включён, но скриншот не пришёл: {exc}",
            reply_markup=headful_main_keyboard(),
        )


async def cancel_command(message: types.Message, state: FSMContext) -> None:
    """Сбросить любое FSM-состояние (в том числе выйти из headful-режима)."""
    if not _is_allowed(message.from_user.id):
        return await _reject(message)

    current = await state.get_state()
    if current and current.startswith("HeadfulState"):
        try:
            await api.headful_exit()
            await message.answer("✅ Вышел из headful-режима. Watcher снова слушает MAX автоматически.")
        except Exception as exc:
            await message.answer(f"⚠️ FSM сброшен, но не удалось выйти из headful: {exc}")

    await state.clear()
    await message.answer("Ок, вышел из режима.")


# ---------- Reply keyboard buttons ----------


async def button_status(message: types.Message) -> None:
    await status_command(message)


async def button_chats(message: types.Message) -> None:
    await chats_command(message)


async def button_help(message: types.Message) -> None:
    await help_command(message)


async def button_reauth(message: types.Message, state: FSMContext) -> None:
    await reauth_command(message, state)


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
        "Слушаю автоматически. Команда /chats — список диалогов.",
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


# ---------- Inline callbacks (reply) ----------


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


# ---------- Headful callbacks (управление MAX через inline-кнопки) ----------


async def _send_screenshot(target: types.Message | types.CallbackQuery) -> None:
    """Снять скриншот и прислать его как фото (с кнопками)."""
    chat = target.chat if isinstance(target, types.Message) else target.message.chat
    bot = target.bot
    try:
        png = await api.headful_screenshot()
        await bot.send_photo(
            chat_id=chat.id,
            photo=types.BufferedInputFile(png, filename="max.png"),
            reply_markup=headful_main_keyboard(),
        )
    except Exception as exc:
        await bot.send_message(chat_id=chat.id, text=f"⚠️ Скриншот не пришёл: {exc}")


async def hf_shot_callback(callback: types.CallbackQuery) -> None:
    if not callback.from_user or not _is_allowed(callback.from_user.id):
        return await callback.answer("⛔", show_alert=True)
    await callback.answer("📸")
    await _send_screenshot(callback)


async def hf_reload_callback(callback: types.CallbackQuery) -> None:
    if not callback.from_user or not _is_allowed(callback.from_user.id):
        return await callback.answer("⛔", show_alert=True)
    try:
        await api.headful_reload()
    except Exception as exc:
        return await callback.message.answer(f"⚠️ Reload: {exc}")
    await callback.answer("🔄")
    await _send_screenshot(callback)


async def hf_key_callback(callback: types.CallbackQuery) -> None:
    """Нажата «⏎ Enter» / «⎋ Esc» — нажатие одной клавиши."""
    if not callback.from_user or not _is_allowed(callback.from_user.id):
        return await callback.answer("⛔", show_alert=True)
    if not callback.data:
        return await callback.answer()
    parts = callback.data.split(":", 2)
    if len(parts) < 3:
        return await callback.answer()
    key = parts[2]
    try:
        await api.headful_key(key)
    except Exception as exc:
        return await callback.message.answer(f"⚠️ Key {key}: {exc}")
    await callback.answer(f"⏎ {key}")
    await _send_screenshot(callback)


async def hf_type_callback(callback: types.CallbackQuery, state: FSMContext) -> None:
    """«⌨️ Печатать» — ждём следующее текстовое сообщение и вводим его в активный элемент."""
    if not callback.from_user or not _is_allowed(callback.from_user.id):
        return await callback.answer("⛔", show_alert=True)
    await state.set_state(HeadfulState.waiting_type_text)
    await callback.answer()
    await callback.message.answer(
        "⌨️ Пришлите текст, который нужно напечатать в активном поле MAX.\n"
        "/cancel — отмена."
    )


async def hf_type_text(message: types.Message, state: FSMContext) -> None:
    if not _is_allowed(message.from_user.id):
        return await _reject(message)
    text = message.text or ""
    try:
        await api.headful_type(text)
    except Exception as exc:
        await message.answer(f"⚠️ Type: {exc}")
    await state.set_state(HeadfulState.waiting_type_text)
    await _send_screenshot(message)


async def hf_fill_callback(callback: types.CallbackQuery, state: FSMContext) -> None:
    """«🔍 Заполнить поле» — ждём selector, потом значение."""
    if not callback.from_user or not _is_allowed(callback.from_user.id):
        return await callback.answer("⛔", show_alert=True)
    await state.set_state(HeadfulState.waiting_fill_selector)
    await callback.answer()
    await callback.message.answer(
        "🔍 Шаг 1/2. Пришлите CSS-селектор поля, которое нужно заполнить "
        "(например, <code>input[name=\"phone\"]</code>).\n"
        "/cancel — отмена.",
        parse_mode="HTML",
    )


async def hf_fill_selector(message: types.Message, state: FSMContext) -> None:
    if not _is_allowed(message.from_user.id):
        return await _reject(message)
    await state.update_data(fill_selector=(message.text or "").strip())
    await state.set_state(HeadfulState.waiting_fill_value)
    await message.answer("🔍 Шаг 2/2. Пришлите значение, которое нужно вставить в это поле.")


async def hf_fill_value(message: types.Message, state: FSMContext) -> None:
    if not _is_allowed(message.from_user.id):
        return await _reject(message)
    data = await state.get_data()
    selector = data.get("fill_selector")
    if not selector:
        await state.set_state(HeadfulState.waiting_type_text)
        await message.answer("Что-то пошло не так с селектором. Попробуйте ещё раз.")
        return
    value = message.text or ""
    try:
        await api.headful_fill(selector, value)
    except Exception as exc:
        await message.answer(f"⚠️ Fill: {exc}")
    await state.set_state(HeadfulState.waiting_type_text)
    await _send_screenshot(message)


async def hf_click_callback(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not _is_allowed(callback.from_user.id):
        return await callback.answer("⛔", show_alert=True)
    await state.set_state(HeadfulState.waiting_fill_value)  # переиспользуем стейт: ввод селектора
    await callback.answer()
    await callback.message.answer(
        "🖱 Пришлите CSS-селектор кнопки/ссылки, на которую нужно кликнуть.\n"
        "/cancel — отмена."
    )


async def hf_wait_callback(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not _is_allowed(callback.from_user.id):
        return await callback.answer("⛔", show_alert=True)
    await state.set_state(HeadfulState.waiting_wait_selector)
    await callback.answer()
    await callback.message.answer(
        "⏳ Пришлите CSS-селектор элемента, который нужно дождаться "
        "(например, <code>.chats-list</code>).\n/cancel — отмена.",
        parse_mode="HTML",
    )


async def hf_wait_selector(message: types.Message, state: FSMContext) -> None:
    if not _is_allowed(message.from_user.id):
        return await _reject(message)
    selector = (message.text or "").strip()
    try:
        await api.headful_wait(selector, timeout=10.0)
    except Exception as exc:
        await message.answer(f"⚠️ Wait: {exc}")
    await state.set_state(HeadfulState.waiting_type_text)
    await _send_screenshot(message)


async def hf_nav_callback(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not _is_allowed(callback.from_user.id):
        return await callback.answer("⛔", show_alert=True)
    await state.set_state(HeadfulState.waiting_navigate_url)
    await callback.answer()
    await callback.message.answer(
        "🌐 Пришлите URL, по которому нужно перейти (например, https://web.max.ru).\n"
        "/cancel — отмена."
    )


async def hf_navigate_url(message: types.Message, state: FSMContext) -> None:
    if not _is_allowed(message.from_user.id):
        return await _reject(message)
    url = (message.text or "").strip()
    try:
        await api.headful_navigate(url)
    except Exception as exc:
        await message.answer(f"⚠️ Navigate: {exc}")
    await state.set_state(HeadfulState.waiting_type_text)
    await _send_screenshot(message)


async def hf_scroll_callback(callback: types.CallbackQuery) -> None:
    if not callback.from_user or not _is_allowed(callback.from_user.id):
        return await callback.answer("⛔", show_alert=True)
    delta = 400 if callback.data == "hf:scroll" else -400
    try:
        await api.headful_scroll(delta_y=delta)
    except Exception as exc:
        return await callback.message.answer(f"⚠️ Scroll: {exc}")
    await callback.answer("↕️")
    await _send_screenshot(callback)


async def hf_clear_callback(callback: types.CallbackQuery) -> None:
    if not callback.from_user or not _is_allowed(callback.from_user.id):
        return await callback.answer("⛔", show_alert=True)
    try:
        await api.headful_clear_cookies()
    except Exception as exc:
        return await callback.message.answer(f"⚠️ Clear: {exc}")
    await callback.answer("🧹")
    await callback.message.answer(
        "Cookies очищены. Можно перезагрузить страницу MAX (кнопка «🔄 Обновить»)."
    )


async def hf_done_callback(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not _is_allowed(callback.from_user.id):
        return await callback.answer("⛔", show_alert=True)
    await state.clear()
    try:
        await api.headful_exit()
        await callback.message.answer(
            "✅ Готово. Вышел из headful-режима, watcher снова слушает MAX автоматически."
        )
    except Exception as exc:
        await callback.message.answer(f"⚠️ Не удалось выйти из headful: {exc}")
    await callback.answer()


async def hf_cancel_callback(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not _is_allowed(callback.from_user.id):
        return await callback.answer("⛔", show_alert=True)
    await state.clear()
    await callback.answer("Отменено")


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
    dp.message.register(button_reauth, F.text == "🔐 /reauth")

    dp.message.register(
        reply_text, ReplyState.waiting_text, F.content_type == "text"
    )
    dp.message.register(
        reply_media,
        ReplyState.waiting_text,
        F.content_type.in_({"photo", "video", "video_note", "voice", "audio", "document"}),
    )

    # Headful FSM: ввод текста / селекторов / URL
    dp.message.register(
        hf_type_text, HeadfulState.waiting_type_text, F.content_type == "text"
    )
    dp.message.register(
        hf_fill_selector, HeadfulState.waiting_fill_selector, F.content_type == "text"
    )
    dp.message.register(
        hf_fill_value, HeadfulState.waiting_fill_value, F.content_type == "text"
    )
    dp.message.register(
        hf_wait_selector, HeadfulState.waiting_wait_selector, F.content_type == "text"
    )
    dp.message.register(
        hf_navigate_url, HeadfulState.waiting_navigate_url, F.content_type == "text"
    )

    dp.callback_query.register(reply_callback, F.callback_data.startswith("reply:"))
    dp.callback_query.register(showid_callback, F.callback_data.startswith("showid:"))
    dp.callback_query.register(history_callback, F.callback_data.startswith("history:"))

    # Headful inline callbacks
    dp.callback_query.register(hf_shot_callback, F.callback_data == "hf:shot")
    dp.callback_query.register(hf_reload_callback, F.callback_data == "hf:reload")
    dp.callback_query.register(hf_type_callback, F.callback_data == "hf:type")
    dp.callback_query.register(hf_fill_callback, F.callback_data == "hf:fill")
    dp.callback_query.register(hf_click_callback, F.callback_data == "hf:click")
    dp.callback_query.register(hf_wait_callback, F.callback_data == "hf:wait")
    dp.callback_query.register(hf_nav_callback, F.callback_data == "hf:nav")
    dp.callback_query.register(hf_scroll_callback, F.callback_data.in_({"hf:scroll", "hf:scrollup"}))
    dp.callback_query.register(hf_clear_callback, F.callback_data == "hf:clear")
    dp.callback_query.register(hf_done_callback, F.callback_data == "hf:done")
    dp.callback_query.register(hf_cancel_callback, F.callback_data == "hf:cancel")
    dp.callback_query.register(hf_key_callback, F.callback_data.startswith("hf:key:"))