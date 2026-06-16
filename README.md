# MAX ↔ Telegram Bridge

Личный «мост» между веб-версией мессенджера MAX и Telegram-ботом, вдохновлённый
публикацией daryahenna. Сервис запускает headless Chromium через Playwright,
авторизуется в MAX Web, читает новые сообщения/медиа и пересылает их в
Telegram-бот, а из бота позволяет отвечать — сообщения уходят обратно в нужный
чат MAX.

## Возможности

- Авторизация в MAX Web: первичная ручная (`make reauth` локально) или
  автоматическая с поддержкой 2FA (TOTP из переменных окружения или ручной
  ввод кода через бота).
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
├── Dockerfile              # монолитный, supervisord поднимает 3 процесса
├── supervisord.conf        # конфиг supervisor (api/bot/watcher)
├── .env.example            # шаблон переменных окружения
├── README.md
├── api/                    # FastAPI сервис
├── bot/                    # aiogram бот
├── watcher/                # Playwright воркер
└── shared/                 # общий код (db, http_client, config, …)
```

## Деплой на Railway

Railway — это «один Dockerfile = один сервис». Поэтому все три процесса
(`api`, `bot`, `watcher`) крутятся внутри одного контейнера под
управлением [supervisord](http://supervisord.org/).

### 1. Создайте сервис
В Railway создайте **Service → Deploy from GitHub Repo** (или Empty Service
→ подключите репозиторий). В настройках укажите:
- **Root Directory**: `max-telegram-bridge`
- **Dockerfile Path**: `Dockerfile` (по умолчанию)

### 2. Задайте переменные окружения
В разделе **Variables** добавьте (значения из `.env.example`):

| Имя | Описание |
| --- | --- |
| `BRIDGE_API_KEY` | **обязательно.** Сгенерируйте: `openssl rand -hex 32` |
| `TELEGRAM_BOT_TOKEN` | токен из `@BotFather` |
| `ALLOWED_TG_USER_IDS` | ваш numeric Telegram id (через запятую, если несколько) |
| `MAX_PHONE` | номер телефона MAX в формате `+79xxxxxxxxx` |
| `MAX_PASSWORD` | пароль MAX |
| `MAX_TOTP_SECRET` | (опц.) TOTP-секрет 2FA в base32 |
| `MAX_WEB_URL` | (опц.) по умолчанию `https://web.max.ru` |
| `API_HOST` | (опц.) `0.0.0.0` |
| `API_PORT` | (опц.) `8000` |
| `DB_PATH` | (опц.) `/data/bridge.db` |
| `MEDIA_DIR` | (опц.) `/data/media` |
| `PROFILE_DIR` | (опц.) `/data/max-profile` |
| `WATCHER_POLL_INTERVAL` | (опц.) `1.5` |
| `WATCHER_HEALTH_INTERVAL` | (опц.) `30` |
| `WATCHER_HISTORY_BACKFILL` | (опц.) `50` |
| `LOG_LEVEL` | (опц.) `INFO` |

> ⚠️ Если `BRIDGE_API_KEY` не задан, мост **не стартует** — это сделано
> специально, чтобы случайно не сгенерировать разные ключи в разных
> процессах.

### 3. Настройте Volume
Чтобы база `bridge.db`, профиль MAX и медиа не терялись при редеплое,
в разделе **Settings → Volumes** создайте Volume и смонтируйте в `/data`.

### 4. Networking
Railway сам проксирует порт 8000. В **Settings → Networking** убедитесь,
что порт `8000` отмечен как публичный (нужно для `/health` и для api).

### 5. Deploy
Нажмите **Deploy**. В логах вы увидите stdout трёх процессов
(`api`, `bot`, `watcher`) — каждый со своим префиксом.

### 6. Проверьте
- В Telegram откройте бота и отправьте `/start`.
- Если MAX не авторизован — бот пришлёт инструкцию по `/reauth`.

## Первичная авторизация MAX

В Railway интерактивный вход в MAX через `HEADFUL=1` невозможен
(нет дисплея). Варианты:

1. **Локально** (рекомендуется): поднять мост `docker compose up -d --build`
   (нужен `docker-compose.yaml` — в репозитории его больше нет, см. раздел
   "Локальная разработка") или даже `python run.py` в `watcher/`
   с `HEADFUL=1`, войти в MAX, затем скопировать `/data/max-profile`
   в Railway Volume.
2. **Через TOTP**: если указан `MAX_TOTP_SECRET`, мост пройдёт 2FA сам
   при первом запуске. Для самого первого входа всё равно потребуется
   сессия — поэтому вариант 1 надёжнее.

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
- Все внутренние HTTP-вызовы авторизуются заголовком
  `X-Api-Key: $BRIDGE_API_KEY`.
- Cookies MAX лежат в `/data/max-profile`; рекомендуется шифровать диск
  и не выкладывать Volume публично.
- В логах секреты маскируются (см. `shared/logging.py`).

## Ограничения

- Telegram Bot API ограничивает загрузку 50 МБ на одну отправку; файлы
  больше не будут пересланы (но останутся в MAX).
- При изменении DOM MAX Web возможны сбои чтения/отправки — потребуется
  обновить селекторы в `watcher/app/`.

## Локальная разработка

Для локальной разработки можно поднять всё в одном контейнере тем же
`Dockerfile`:
```bash
docker build -t max-bridge .
docker run --rm -it \
  -p 8000:8000 \
  -v $(pwd)/data:/data \
  --env-file .env \
  max-bridge
```

Или запустить процессы по отдельности в разных терминалах, без Docker:
```bash
# Терминал 1 — api
cd api && uvicorn main:app --reload --port 8000

# Терминал 2 — bot
cd bot && python run.py

# Терминал 3 — watcher
cd watcher && HEADFUL=1 python -m app.auth --setup
# после входа в MAX:
cd watcher && python run.py