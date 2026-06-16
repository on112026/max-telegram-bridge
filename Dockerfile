# syntax=docker/dockerfile:1.7
#
# Единый multi-stage Dockerfile для max-telegram-bridge.
# Сборка:
#   docker compose build api
#   docker compose build bot
#   docker compose build watcher
# Каждый сервис указывает target: api|bot|watcher.

# ---------- Общая база для api и bot ----------
FROM python:3.11-slim AS base
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app


# ---------- API (FastAPI) ----------
FROM base AS api
COPY api/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY shared /app/shared
COPY api    /app/api

ENV PYTHONPATH=/app:/app/api
WORKDIR /app/api
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]


# ---------- Bot (aiogram) ----------
FROM base AS bot
COPY bot/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY shared /app/shared
COPY bot    /app/bot

ENV PYTHONPATH=/app:/app/bot
WORKDIR /app/bot
CMD ["python", "run.py"]


# ---------- Watcher (Playwright Chromium) ----------
FROM mcr.microsoft.com/playwright/python:v1.49.1-jammy AS watcher
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app

# Системные библиотеки, нужные headless Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
        fonts-liberation \
        libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 \
        libgbm1 libpango-1.0-0 libcairo2 libasound2 libxcomposite1 libxdamage1 \
        libxrandr2 libxfixes3 libxshmfence1 libxext6 libx11-6 libxcb1 libdbus-1-3 \
    && rm -rf /var/lib/apt/lists/*

COPY watcher/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt \
 && pip install --no-cache-dir playwright==1.49.1

COPY shared  /app/shared
COPY watcher /app/watcher

ENV PYTHONPATH=/app:/app/watcher
WORKDIR /app/watcher
CMD ["python", "run.py"]