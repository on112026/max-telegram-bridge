FROM mcr.microsoft.com/playwright/python:v1.49.1-jammy

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app:/app/watcher

# Системные пакеты
RUN apt-get update && apt-get install -y --no-install-recommends \
        fonts-liberation \
        libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 \
        libgbm1 libpango-1.0-0 libcairo2 libasound2 libxcomposite1 libxdamage1 \
        libxrandr2 libxfixes3 libxshmfence1 libxext6 libx11-6 libxcb1 libdbus-1-3 \
    && rm -rf /var/lib/apt/lists/*

COPY watcher/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Playwright Python уже установлен внутри образа, но версия должна совпадать
# Переустановим на нужную для воспроизводимости
RUN pip install --no-cache-dir playwright==1.49.1

COPY shared /app/shared
COPY watcher /app/watcher

WORKDIR /app/watcher
CMD ["python", "run.py"]