SHELL := /bin/bash
.DEFAULT_GOAL := start
.NOTPARALLEL:

POSTGRES_PORT ?= 5433
REDIS_PORT ?= 6379
API_PORT ?= 8000
CLIP_PORT ?= 8082
MINIO_API_PORT ?= 9000
MINIO_CONSOLE_PORT ?= 9001
DATABASE_URL ?= postgresql+psycopg://readforge:readforge@localhost:$(POSTGRES_PORT)/readforge
REDIS_URL ?= redis://localhost:$(REDIS_PORT)/0
CLIP_API_URL ?= http://localhost:$(CLIP_PORT)/
MEDIA_BUCKET_PROVIDER ?= cloudflare
MINIO_ENDPOINT ?= http://localhost:$(MINIO_API_PORT)
MINIO_ACCESS_KEY ?= minioadmin
MINIO_SECRET_KEY ?= minioadmin
MINIO_BUCKET_NAME ?= readforge-documents

export POSTGRES_PORT DATABASE_URL REDIS_PORT REDIS_URL CLIP_PORT CLIP_API_URL
export MEDIA_BUCKET_PROVIDER MINIO_API_PORT MINIO_CONSOLE_PORT MINIO_ENDPOINT
export MINIO_ACCESS_KEY MINIO_SECRET_KEY MINIO_BUCKET_NAME

RUN_DIR := .run
API_PID := $(RUN_DIR)/api.pid
WORKER_PID := $(RUN_DIR)/worker.pid

.PHONY: setup start up stop down restart status sync db redis clip media minio migrate api worker logs

setup: sync db redis clip media migrate

start: api worker

up: start

sync:
	@uv sync

db:
	@if docker compose ps --status running --services | grep -qx postgres; then \
		echo "PostgreSQL already running"; \
	else \
		docker compose up -d postgres; \
	fi
	@for _ in {1..30}; do \
		docker compose exec -T postgres pg_isready -U readforge -d readforge >/dev/null 2>&1 && exit 0; \
		sleep 1; \
	done; echo "PostgreSQL did not become ready"; exit 1

redis: sync
	@if REDIS_URL="$(REDIS_URL)" uv run python -c 'import os, redis; redis.Redis.from_url(os.environ["REDIS_URL"]).ping()' >/dev/null 2>&1; then \
		echo "Redis already running"; \
	else \
		docker compose up -d redis; \
	fi
	@for _ in {1..30}; do \
		REDIS_URL="$(REDIS_URL)" uv run python -c 'import os, redis; redis.Redis.from_url(os.environ["REDIS_URL"]).ping()' >/dev/null 2>&1 && exit 0; \
		sleep 1; \
	done; echo "Redis did not become ready"; exit 1

clip:
	@if curl -fsS "$(CLIP_API_URL)openapi.json" >/dev/null 2>&1; then \
		echo "CLIP already running"; \
	elif docker compose ps --status running --services | grep -qx clip; then \
		echo "Waiting for CLIP"; \
	else \
		docker compose up -d clip; \
	fi
	@for _ in {1..180}; do \
		curl -fsS "$(CLIP_API_URL)openapi.json" >/dev/null 2>&1 && exit 0; \
		sleep 1; \
	done; echo "CLIP did not become ready at $(CLIP_API_URL)"; exit 1

media:
	@if [ "$(MEDIA_BUCKET_PROVIDER)" = "minio" ]; then \
		$(MAKE) --no-print-directory minio; \
	else \
		echo "Media bucket: Cloudflare R2 (checked by the application)"; \
	fi

minio:
	@if curl -fsS "$(MINIO_ENDPOINT)/minio/health/live" >/dev/null 2>&1; then \
		echo "MinIO already running"; \
	elif docker compose ps --status running --services | grep -qx minio; then \
		echo "Waiting for MinIO"; \
	else \
		docker compose up -d minio; \
	fi
	@for _ in {1..30}; do \
		curl -fsS "$(MINIO_ENDPOINT)/minio/health/live" >/dev/null 2>&1 && exit 0; \
		sleep 1; \
	done; echo "MinIO did not become ready at $(MINIO_ENDPOINT)"; exit 1

migrate: sync db
	@uv run readforge-migrate

api: sync db redis
	@mkdir -p $(RUN_DIR)
	@if [ -f "$(API_PID)" ] && kill -0 "$$(cat $(API_PID))" 2>/dev/null; then \
		echo "API already running (PID $$(cat $(API_PID)))"; \
	elif lsof -tiTCP:$(API_PORT) -sTCP:LISTEN >/dev/null 2>&1; then \
		echo "API port $(API_PORT) already has a running process"; \
	else \
		rm -f "$(API_PID)"; \
		nohup uv run fastapi run src/readforge/server.py --port $(API_PORT) >$(RUN_DIR)/api.log 2>&1 & \
		echo $$! >"$(API_PID)"; \
		echo "API started (PID $$(cat $(API_PID)))"; \
	fi

worker: sync db redis clip media
	@mkdir -p $(RUN_DIR)
	@if [ -f "$(WORKER_PID)" ] && kill -0 "$$(cat $(WORKER_PID))" 2>/dev/null; then \
		echo "Worker already running (PID $$(cat $(WORKER_PID)))"; \
	elif pgrep -f '[r]eadforge-worker' >/dev/null 2>&1; then \
		echo "Worker already running outside this Makefile"; \
	else \
		rm -f "$(WORKER_PID)"; \
		nohup uv run readforge-worker >$(RUN_DIR)/worker.log 2>&1 & \
		echo $$! >"$(WORKER_PID)"; \
		echo "Worker started (PID $$(cat $(WORKER_PID)))"; \
	fi

status:
	@docker compose ps
	@if lsof -tiTCP:$(API_PORT) -sTCP:LISTEN >/dev/null 2>&1; then echo "API: running"; else echo "API: stopped"; fi
	@if pgrep -f '[r]eadforge-worker' >/dev/null 2>&1; then echo "Worker: running"; else echo "Worker: stopped"; fi
	@if curl -fsS "$(CLIP_API_URL)openapi.json" >/dev/null 2>&1; then echo "CLIP: running"; else echo "CLIP: stopped"; fi
	@if [ "$(MEDIA_BUCKET_PROVIDER)" = "minio" ]; then \
		if curl -fsS "$(MINIO_ENDPOINT)/minio/health/live" >/dev/null 2>&1; then echo "MinIO: running"; else echo "MinIO: stopped"; fi; \
	else \
		echo "Media bucket: Cloudflare R2 (checked by the application)"; \
	fi

logs:
	@mkdir -p $(RUN_DIR)
	@touch $(RUN_DIR)/api.log $(RUN_DIR)/worker.log
	@tail -f $(RUN_DIR)/api.log $(RUN_DIR)/worker.log

stop:
	@if [ -f "$(API_PID)" ] && kill -0 "$$(cat $(API_PID))" 2>/dev/null; then kill "$$(cat $(API_PID))"; fi
	@if [ -f "$(WORKER_PID)" ] && kill -0 "$$(cat $(WORKER_PID))" 2>/dev/null; then kill "$$(cat $(WORKER_PID))"; fi
	@rm -f $(API_PID) $(WORKER_PID)
	@docker compose stop postgres redis clip minio >/dev/null
	@echo "ReadForge stopped"

down: stop
	@docker compose down

restart: stop start
