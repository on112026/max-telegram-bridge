# MAX ↔ Telegram Bridge

Личный «мост» между веб-версией мессенджера MAX и Telegram-ботом. Сервис
запускает Chromium через Playwright, авторизуется в MAX Web, читает новые
сообщения/медиа и пересылает их в Telegram-бот, а из бота позволяет отвечать —
сообщения уходят обратно в нужный чат MAX.

Если автоматический логин не сработал (капча, 2FA, смена пароля и т. п.),
есть **управляемый экран**: встроенный Xvfb + x11vnc + noVNC, к которому
можно подключиться как прямо из Telegram (команда `/reauth`, inline-кнопки
и скриншоты), так и через браузер по адресу `/vnc`.

## Возможности

- Авторизация в MAX Web: автоматически (с поддержкой TOTP) **или вручную
  через `/reauth`** — бот пришлёт скриншоты и панель кнопок для ввода
  данных; параллельно к виртуальному дисплею можно подключиться noVNC'ом.
- Перехват новых сообщений: WebSocket + XHR + DOM-фолбэк, дедупликация
  по `(chat_id, message_id)`.
- Пересылка текстовых, фото-, видео-, голосовых, видео-кружочков и
  файловых сообщений в Telegram.
- Ответ из Telegram в нужный чат MAX (text, photo, video, voice,
  video_note, document).
- История чата по запросу (`/history <chat_id>`).
- Защита `ALLOWED_TG_USER_IDS`: бот отвечает только авторизованному
  пользователю.
- Хранение сессии MAX в persistent-профиле (`/data/max-profile`),
  устойчивость к рестартам.

## Стек

| Сервис | Назначение | Технологии |
| --- | --- | --- |
| `api` | внутренний шлюз, очередь событий и команд, прокси на watcher и noVNC | FastAPI + SQLAlchemy + SQLite + aiohttp |
| `bot` | Telegram-интерфейс (включая FSM для headful) | aiogram 3 + httpx |
| `watcher` | Playwright Chromium, чтение/отправка MAX, headful-controller | Playwright (Python) + aiohttp |
| `xvfb` | виртуальный дисплей 1280×800×24 | Xvfb |
| `x11vnc` | VNC-сервер на :5900 (RFB) | x11vnc |
| `novnc` | HTML5-обёртка над VNC (WebSocket) | websockify + noVNC |

## Структура

```
max-telegram-bridge/
├── Dockerfile              # монолитный + multi-stage для noVNC
├── supervisord.conf        # 6 процессов: xvfb, x11vnc, novnc, api, bot, watcher
├── entrypoint.sh           # генерирует vnc-пароль и стартует supervisord
├── .env.example            # шаблон переменных окружения
├── README.md
├── api/                    # FastAPI сервис (проксирует /watcher/headful/* и /vnc/*)
├── bot/                    # aiogram бот + FSM /reauth
├── watcher/                # Playwright воркер + headful_api + headful controller
└── shared/                 # общий код (db, http_client, config, log_setup, …)
```

## Деплой на Railway

Railway — это «один Dockerfile = один сервис». Поэтому все процессы
(`api`, `bot`, `watcher`, `xvfb`, `x11vnc`, `novnc`) крутятся внутри
одного контейнера под управлением [supervisord](http://supervisord.org/).

### 1. Создайте сервис
В Railway создайте **Service → Deploy from GitHub Repo** (или Empty
Service → подключите репозиторий). В настройках укажите:
- **Root Directory**: `max-telegram-bridge`
- **Dockerfile Path**: `Dockerfile` (по умолчанию)

### 2. Задайте переменные окружения
В разделе **Variables** добавьте (значения из `.env.example`):

| Имя | Описание |
| --- | --- |
| `BRIDGE_API_KEY` | **обязательно.** Сгенерируйте: `openssl rand -hex 32` |
| `TELEGRAM_BOT_TOKEN` | токен из `@BotFather` |
| `ALLOWED_TG_USER_IDS` | ваш numeric Telegram id (через запятую) |
| `MAX_PHONE` | номер телефона MAX в формате `+79xxxxxxxxx` |
| `MAX_PASSWORD` | пароль MAX |
| `MAX_TOTP_SECRET` | (опц.) TOTP-секрет 2FA в base32 |
| `MAX_WEB_URL` | (опц.) по умолчанию `https://web.max.ru` |
| `API_HOST` / `API_PORT` | (опц.) `0.0.0.0` / `8000` |
| `DB_PATH` / `MEDIA_DIR` / `PROFILE_DIR` | (опц.) `/data/bridge.db` и т. д. |
| `WATCHER_POLL_INTERVAL` | (опц.) `1.5` |
| `WATCHER_HEADFUL_DEFAULT` | (опц.) `0` — на проде headful включается через `/reauth` |
| `VNC_PASSWORD` | **обязательно.** Пароль для noVNC и Telegram-управления. Смените `changeme`! |
| `VNC_PUBLIC` | (опц.) `1` — открыть `/vnc` публично; `0` — отдавать 404 |
| `NOVNC_PORT` | (опц.) `6080` |
| `LOG_LEVEL` | (опц.) `INFO` |

> ⚠️ Если `BRIDGE_API_KEY` не задан, мост **не стартует** — это сделано
> специально, чтобы случайно не сгенерировать разные ключи в разных
> процессах.

### 3. Настройте Volume
В **Settings → Volumes** смонтируйте Volume в `/data` — там будут
`bridge.db`, профиль MAX, скачанные медиа и, опционально, `vnc_password`.

### 4. Networking
Публичный порт — только `8000`. Через него доступны:
- `GET /health` — health-check Railway
- `POST /events`, `POST /send`, `GET /chats`, … — API моста
- `POST /watcher/headful/*` — прокси на watcher (нужен `X-Api-Key`)
- `GET  /vnc`, `GET /vnc/*` — HTML5-обёртка над Chromium (см. ниже)
- `WS   /vnc/websockify` — WebSocket-прокси к VNC

### 5. Deploy
Нажмите **Deploy**. В логах увидите stdout шести процессов с префиксами
(`xvfb`, `x11vnc`, `novnc`, `api`, `bot`, `watcher`).

### 6. Проверьте
- В Telegram откройте бота и отправьте `/start`.
- Если MAX не авторизован — бот сам предложит `/reauth`.

## Ручная авторизация MAX

Если у MAX-сессии слетела авторизация (2FA-код, капча, «введите пароль
заново» и т. п.), у вас два равноценных способа её восстановить.

### Способ A — через Telegram (`/reauth`)

1. Отправьте боту команду `/reauth` (или нажмите кнопку «🔐 /reauth»).
2. Бот переведёт watcher в headful-режим (Chromium откроется на
   виртуальном дисплее Xvfb) и пришлёт скриншот.
3. Управляйте через inline-кнопки под скриншотом:
   - `⌨️ Печатать` — бот ждёт ваше сообщение, вводит его в активное
     поле MAX.
   - `🔍 Заполнить поле` — бот ждёт CSS-селектор, потом значение
     (например, `input[name="phone"]` → `+79…`).
   - `🖱 Кликнуть` — бот ждёт CSS-селектор кнопки.
   - `⏎ Enter` / `⎋ Esc` — нажатие одной клавиши.
   - `⏳ Ждать элемент` — дождаться появления элемента.
   - `🌐 Открыть URL` — перейти по URL.
   - `⬇️` / `⬆️` — прокрутить.
   - `🧹 Очистить cookies` — пригодится, если сайт «залип».
   - `🔄 Обновить` — `F5`.
   - `📸 Скриншот` — прислать свежий снимок.
   - `✅ Готово (выйти)` — выйти из headful, watcher возобновит
     автослушивание.
   - `❌ Отмена` — выйти без сохранения.

   Не знаете CSS-селектор? Откройте ту же страницу в `/vnc` (способ B) —
   ПКМ → «Inspect» в обычном Chrome.

4. После успешного входа нажмите «✅ Готово» — watcher сам перезапустит
   listener и продолжит работу в обычном режиме.

### Способ B — через noVNC (`/vnc` в браузере)

1. Откройте `<адрес-railway>/vnc` — это HTML-страница с noVNC.
2. noVNC попросит пароль — это `VNC_PASSWORD` из переменных окружения.
3. Вы увидите тот же виртуальный дисплей: Chromium с открытым MAX.
4. Войдите в MAX вручную (мышь, клавиатура, скролл, всё как обычно).
5. Закройте вкладку. По окончании сессии бот пошлёт вам в Telegram
   уведомление; либо отправьте `/reauth → ✅ Готово` явно.

> Пока вы в `/vnc` или в `/reauth`, обычная очередь MAX-событий
> приостановлена — чтобы вы и бот не «били» по одной и той же сессии.

## Команды бота

- `/start`, `/help`
- `/status` — статус сессии MAX, длина очереди, последний синк.
- `/chats` — список MAX-чатов с их `chat_id`.
- `/reply <chat_id>` — следующее ваше сообщение/медиа уйдёт в этот чат.
- `/history <chat_id> [N=20]` — подтянуть последние N сообщений чата.
- `/reauth` — открыть управляемый экран MAX (бот пришлёт скриншоты).
- `/cancel` — выйти из любого FSM-режима (включая headful).

## Безопасность

- Бот принимает команды только от `ALLOWED_TG_USER_IDS`.
- Все внутренние HTTP-вызовы авторизуются заголовком
  `X-Api-Key: $BRIDGE_API_KEY`.
- `/vnc` защищён VNC-паролем (`VNC_PASSWORD`). Без него — пустой экран.
- Cookies MAX лежат в `/data/max-profile`; рекомендуется шифровать диск
  и не выкладывать Volume публично.
- В логах секреты маскируются (см. `shared/log_setup.py`).

## Ограничения

- Telegram Bot API ограничивает загрузку 50 МБ на одну отправку; файлы
  больше не будут пересланы (но останутся в MAX).
- При изменении DOM MAX Web возможны сбои чтения/отправки — потребуется
  обновить селекторы в `watcher/app/`.
- noVNC внутри контейнера — это single-user: пока вы управляете MAX
  через Telegram или `/vnc`, обычные MAX-события не форвардятся в
  Telegram. После выхода из headful всё возобновляется.

## Локальная разработка

```bash
docker build -t max-bridge .
docker run --rm -it \
  -p 8000:8000 \
  -v $(pwd)/data:/data \
  --env-file .env \
  max-bridge
```

После старта откройте `http://localhost:8000/vnc` — увидите тот же
виртуальный дисплей, что и в Railway.

Или запустите процессы по отдельности в разных терминалах, без Docker:
```bash
# Терминал 1 — api
cd api && uvicorn main:app --reload --port 8000

# Терминал 2 — bot
cd bot && python run.py

# Терминал 3 — watcher (headful для локального дебага)
cd watcher && HEADFUL=1 python run.py