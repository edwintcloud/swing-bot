SHELL := /bin/sh

COMPOSE := docker compose
PAPER_COMPOSE := env -u TWS_ACCOUNT -u TRADING_MODE -u IB_HOST -u IB_PORT \
	-u LIVE_TRADING_ACK docker compose --env-file .env
LIVE_COMPOSE := docker compose -f docker-compose.yml -f docker-compose.live.yml
CONTRACTS ?= data/contracts.json
CATALOG ?= data/catalog
BACKTEST_START ?= 2026-01-01T00:00:00-05:00
BACKTEST_END ?= 2026-08-20T20:00:00-04:00
BACKTEST_EQUITY ?= 100000
BACKTEST_OUTPUT ?= reports/latest

.PHONY: backtest paper live stop logs status test

backtest:
	uv run swing-bot backtest --contracts $(CONTRACTS) --catalog $(CATALOG) \
		--start $(BACKTEST_START) --end $(BACKTEST_END) \
		--starting-equity $(BACKTEST_EQUITY) --output $(BACKTEST_OUTPUT)

paper:
	$(PAPER_COMPOSE) up -d --build bot dashboard

live:
	@case "$(TWS_ACCOUNT)" in U*) ;; *) echo "TWS_ACCOUNT must be a live account beginning with U" >&2; exit 1;; esac
	@test "$(LIVE_TRADING_ACK)" = "I_UNDERSTAND_LIVE_ORDERS_ARE_REAL" || \
		{ echo "Set LIVE_TRADING_ACK=I_UNDERSTAND_LIVE_ORDERS_ARE_REAL" >&2; exit 1; }
	$(LIVE_COMPOSE) up -d --build bot dashboard

stop:
	$(COMPOSE) stop dashboard bot

logs:
	$(COMPOSE) logs -f bot dashboard

status:
	$(COMPOSE) ps

test:
	uv run pytest
	uv run ruff check .