FROM python:3.11-slim

WORKDIR /app

# Зависимости ставим ДКОМ-копированием shared как "библиотеку"
COPY api/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Подключаем shared как пакет
COPY shared /app/shared
COPY api /app/api

# Делаем /app рабочим каталогом, чтобы import shared работал
ENV PYTHONPATH=/app:/app/api
ENV PYTHONUNBUFFERED=1

WORKDIR /app/api
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]