# MAX ↔ Telegram Bridge

Личный «мост» между веб-версией мессенджера MAX и Telegram-ботом, вдохновлённый
публикацией daryahenna. Сервис запускает headless Chromium через Playwright,
авторизуется в MAX Web, читает новые сообщения/медиа и пересылает их в
Telegram-бот, а из бота позволяет отвечать — сообщения уходят обратно в нужный
чат MAX.

## Возможности

- Авторизация в MAX Web: первичная ручная (`make reauth`) или автоматическая
  с поддержкой 2FA (TOTP из `.env` или ручной ввод кода через бота).
- Перехват новых сообщений: WebSocket + XHR + DOM-фолбэк, дедупликация по
  `(chat_id, message_id)`.
- Пересылка текстовых, фото-, видео-, голосовых, видео-кружочков и файловых
  сообщений в Telegram.
- Ответ из Telegram в нужный чат MAX (text, photo, video, voice, video_note,
  document).
- История чата по запросу (`/history <chat_id>`).
- Защита `ALLOWED_TG_USER_IDS`: бот отвечает только авторизованному
  пользователю.
- Хранение сессии MAX в persistent-профиле (`/data/max-profile`), устойчивость
  к рестартам.

## Стек

| Сервис | Назначение | Технологии |
| --- | --- | --- |
| `api` | внутренний шлюз, очередь событий и команд | FastAPI + SQLAlchemy + SQLite |
| `bot` | Telegram-интерфейс | aiogram 3 + aiohttp |
| `watcher` | Playwright Chromium, чтение/отправка MAX | Playwright (Python) |

## Структура

```
max-telegram-bridge/
├── docker-compose.yaml
├── Makefile
├── .env.example
├── api/                 # FastAPI сервис
├── bot/                 # aiogram бот
└── watcher/             # Playwright воркер
```

## Подготовка

1. Скопируйте `.env.example` → `.env` и заполните:
   - `TELEGRAM_BOT_TOKEN` — токен бота.
   - `ALLOWED_TG_USER_IDS` — ваш numeric Telegram id (можно узнать у `@userinfobot`).
   - `MAX_PHONE`, `MAX_PASSWORD` — учётные данные MAX.
   - `BRIDGE_API_KEY` — случайная строка 32+ символов (используется между
     сервисами).
   - `MAX_TOTP_SECRET` (опц.) — TOTP-секрет 2FA (base32). Если не указан, бот
     попросит код у владельца.
2. Запустите:
   ```bash
   make up
   make reauth    # один раз, откроется Chromium, войдите в MAX
   ```
   После успешной авторизации профиль сохранится в `/data/max-profile`.
3. Перезапустите watcher, чтобы он пошёл в headless:
   ```bash
   make restart-watcher
   ```
4. Откройте бота в Telegram, отправьте `/start`.

## Команды бота

- `/start`, `/help`
- `/status` — статус сессии MAX, длина очереди, последний синк.
- `/chats` — список MAX-чатов с их `chat_id`.
- `/reply <chat_id>` — следующее ваше сообщение/медиа уйдёт в этот чат.
- `/history <chat_id> [N=20]` — подтянуть последние N сообщений чата.
- `/reauth` — принудительная переавторизация.
- `/cancel` — выйти из режима ответа.

## Безопасность

- Бот принимает команды только от `ALLOWED_TG_USER_IDS`.
- Все внутренние HTTP-вызовы авторизуются заголовком `X-Api-Key: $BRIDGE_API_KEY`.
- Cookies MAX лежат на volume `bridge-data` под правами root контейнера;
  рекомендуется шифровать диск и не выкладывать volume публично.
- В логах секреты маскируются (см. `shared/logging.py`).

## Ограничения

- Telegram Bot API ограничивает загрузку 50 МБ на одну отправку; файлы больше
  не будут пересланы (но останутся в MAX).
- При изменении DOM MAX Web возможны сбои чтения/отправки — потребуется
  обновить селекторы в `watcher/app/`.