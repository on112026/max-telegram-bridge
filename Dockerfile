# syntax=docker/dockerfile:1.7
#
# Монолитный Dockerfile для max-telegram-bridge.
# Внутри одного контейнера supervisord поднимает три процесса:
# api (FastAPI), bot (aiogram), watcher (Playwright + системный Chromium).
# Подходит для managed-хостингов, где 1 Service = 1 Dockerfile
# (Railway, Render, Koyeb, Fly и т.п.).

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app:/app/api:/app/bot:/app/watcher:/app/shared

# Системные пакеты:
#  - supervisor для управления процессами
#  - chromium для Playwright (без скачивания собственного браузера)
#  - шрифты и библиотеки, нужные headless Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
        supervisor \
        chromium \
        fonts-liberation \
        libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 \
        libgbm1 libpango-1.0-0 libcairo2 libasound2 libxcomposite1 libxdamage1 \
        libxrandr2 libxfixes3 libxshmfence1 libxext6 libx11-6 libxcb1 libdbus-1-3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 1) Зависимости — ставим объединённо
COPY api/requirements.txt     /app/req/api.txt
COPY bot/requirements.txt     /app/req/bot.txt
COPY watcher/requirements.txt /app/req/watcher.txt
RUN pip install --no-cache-dir -r /app/req/api.txt \
 && pip install --no-cache-dir -r /app/req/bot.txt \
 && pip install --no-cache-dir -r /app/req/watcher.txt \
 && pip install --no-cache-dir playwright==1.49.1

# 2) Код
COPY shared  /app/shared
COPY api     /app/api
COPY bot     /app/bot
COPY watcher /app/watcher

# 3) supervisord-конфиг
COPY supervisord.conf /etc/supervisor/conf.d/bridge.conf

# 4) Persistent-директория (для Railway / монолитного деплоя)
RUN mkdir -p /data

EXPOSE 8000
CMD ["supervisord", "-c", "/etc/supervisor/conf.d/bridge.conf"]