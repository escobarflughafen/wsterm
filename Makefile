PY      := .venv/bin/python
STAMP   := $(shell date +%Y%m%d-%H%M%S)
COMPOSE := docker compose

.PHONY: help setup dev test build up down logs shell backup restore import fetch rebuild deploy dev-up

help:            ## list targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-10s %s\n", $$1, $$2}'

setup:           ## create .venv with dev dependencies
	python3.11 -m venv .venv && $(PY) -m pip install -q -r requirements-dev.txt

dev:             ## run locally without auth on 127.0.0.1:8787 (data in ./var)
	ALLOW_NO_AUTH=1 .venv/bin/uvicorn --app-dir pipeline server:app --host 127.0.0.1 --port 8787 --reload

test:            ## run the test suite
	$(PY) -m pytest -q

build:           ## build the container image
	$(COMPOSE) build

deploy:          ## pull the current branch and rebuild/restart this instance
	git pull --ff-only && $(MAKE) up

dev-up:          ## start this checkout with the dev overlay (live reload, no schedule)
	@test -f .env || (echo "Create .env first: cp .env.example .env" && exit 1)
	$(COMPOSE) -f docker-compose.yml -f docker-compose.dev.yml up -d --build && $(COMPOSE) ps

up:              ## start (detached)
	@test -f .env || (echo "Create .env first: cp .env.example .env" && exit 1)
	$(COMPOSE) up -d --build && $(COMPOSE) ps

down:            ## stop
	$(COMPOSE) down

logs:            ## follow logs
	$(COMPOSE) logs -f --tail=200

shell:           ## shell inside the container
	$(COMPOSE) exec portfolio bash

backup:          ## tar the data volume to ./backups
	mkdir -p backups && $(COMPOSE) exec -T portfolio tar czf - -C /data --exclude=./exports/staging . > backups/portfolio-$(STAMP).tgz && ls -lh backups | tail -1

restore:         ## restore FILE=backups/x.tgz into the data volume (stop jobs first)
	@test -n "$(FILE)" || (echo "usage: make restore FILE=backups/portfolio-....tgz" && exit 1)
	$(COMPOSE) exec -T portfolio tar xzf - -C /data < $(FILE) && $(COMPOSE) restart portfolio

import:          ## import FILES="a.csv b.csv" through the inbox
	@test -n "$(FILES)" || (echo 'usage: make import FILES="activities.csv holdings.csv"' && exit 1)
	for f in $(FILES); do $(COMPOSE) exec -T portfolio sh -c "mkdir -p /data/exports/inbox && cat > /data/exports/inbox/$$(basename $$f)" < $$f; done
	$(COMPOSE) exec -T portfolio python -c "import sys; sys.path.insert(0,'pipeline'); import store, json; print(json.dumps(store.process_inbox(), indent=1, default=str))"
	$(COMPOSE) exec -T portfolio python pipeline/build_app.py

fetch:           ## fetch due market data inside the container
	$(COMPOSE) exec -T portfolio python pipeline/market_data.py && $(COMPOSE) exec -T portfolio python pipeline/build_app.py

rebuild:         ## recompute data.json inside the container
	$(COMPOSE) exec -T portfolio python pipeline/build_app.py
