.PHONY: up down logs-api logs-bot logs-watcher restart-api restart-bot restart-watcher reauth ps build

SERVICE_COMPOSE = docker compose -f docker-compose.yaml

up:
	$(SERVICE_COMPOSE) up -d --build

down:
	$(SERVICE_COMPOSE) down

ps:
	$(SERVICE_COMPOSE) ps

logs-api:
	$(SERVICE_COMPOSE) logs -f api

logs-bot:
	$(SERVICE_COMPOSE) logs -f bot

logs-watcher:
	$(SERVICE_COMPOSE) logs -f watcher

restart-api:
	$(SERVICE_COMPOSE) restart api

restart-bot:
	$(SERVICE_COMPOSE) restart bot

restart-watcher:
	$(SERVICE_COMPOSE) restart watcher

# Получить интерактивную сессию Playwright для ручной первичной авторизации.
# Запускается вне headless, окно открывается в вашем X-сервере (или с X-Forwarding).
reauth:
	$(SERVICE_COMPOSE) run --rm -e HEADFUL=1 watcher python -m app.auth --setup

build:
	$(SERVICE_COMPOSE) build