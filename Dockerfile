# syntax=docker/dockerfile:1.7
#
# Монолитный Dockerfile для max-telegram-bridge.
# Внутри одного контейнера supervisord поднимает:
#   - api    (FastAPI)
#   - bot    (aiogram)
#   - watcher (Playwright + системный Chromium)
#   - xvfb   (виртуальный X-сервер, чтобы chromium работал в headful-режиме)
#   - x11vnc (стрим экрана :99)
#   - novnc  (HTML5 VNC-клиент на /vnc)
# Подходит для managed-хостингов, где 1 Service = 1 Dockerfile
# (Railway, Render, Koyeb, Fly и т.п.).

# --- Stage 1: noVNC ---
FROM theasp/novnc:latest AS novnc

# --- Stage 2: основной образ ---
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DISPLAY=:99 \
    PYTHONPATH=/app:/app/api:/app/bot:/app/watcher:/app/shared

# Системные пакеты:
#  - supervisor — процесс-менеджер
#  - chromium   — для Playwright
#  - xvfb, x11vnc, websockify, netcat — для headful-режима и noVNC
#  - шрифты и библиотеки для headless/headful Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
        supervisor \
        chromium \
        xvfb \
        x11vnc \
        websockify \
        netcat-openbsd \
        fonts-liberation \
        libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 \
        libgbm1 libpango-1.0-0 libcairo2 libasound2 libxcomposite1 libxdamage1 \
        libxrandr2 libxfixes3 libxshmfence1 libxext6 libx11-6 libxcb1 libdbus-1-3 \
        libxrender1 libxi6 libxtst6 \
    && rm -rf /var/lib/apt/lists/*

# noVNC из отдельного stage
COPY --from=novnc /usr/share/novnc /usr/share/novnc

WORKDIR /app

# 1) Зависимости
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

# 3) supervisord + entrypoint
COPY supervisord.conf /etc/supervisor/conf.d/bridge.conf
COPY entrypoint.sh    /entrypoint.sh
RUN chmod +x /entrypoint.sh

# 4) Persistent-директория (для Railway / монолитного деплоя)
RUN mkdir -p /data /var/log/supervisor

# Порты: 8000 (api), 6080 (noVNC web), 5900 (VNC) — Railway проксирует 8000 и 6080
EXPOSE 8000 6080 5900

ENTRYPOINT ["/entrypoint.sh"]
CMD ["supervisord", "-c", "/etc/supervisor/conf.d/bridge.conf"]