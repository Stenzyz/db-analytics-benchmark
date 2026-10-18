SHELL := /bin/bash
include .env
export

.PHONY: help up down clean env load-ch load-subset bench bench-cold tables all

help:
	@echo "Порядок работы:"
	@echo "  make up          - поднять три СУБД (ClickHouse, PostgreSQL, MySQL)"
	@echo "  make env         - записать характеристики машины в results/environment.txt"
	@echo "  make load-ch     - загрузить NYC Taxi в ClickHouse (идёт фоном, долго)"
	@echo "  make load-subset - перенести подмножество в PostgreSQL и MySQL (Э5)"
	@echo "  make bench       - прогнать все запросы (горячий кэш), собрать summary.csv"
	@echo "  make bench-cold  - прогнать с холодным кэшем (сбросы кэшей ClickHouse)"
	@echo "  make tables      - собрать таблицы результатов в README из summary.csv"
	@echo "  make down        - остановить СУБД"
	@echo "  make clean       - остановить и удалить тома с данными"

up:
	docker compose up -d
	@echo "Ждём готовности СУБД..."
	@docker compose ps

down:
	docker compose down

clean:
	docker compose down -v

env:
	bash scripts/capture_env.sh > results/environment.txt
	@echo "Окружение записано в results/environment.txt — впишите туда CPU/RAM/диск вручную, если не определились автоматически."

load-ch:
	bash scripts/load_clickhouse.sh

load-subset:
	python3 scripts/load_subset.py

bench:
	python3 scripts/run_benchmark.py --mode hot --repeats 5

bench-cold:
	python3 scripts/run_benchmark.py --mode cold --repeats 5

tables:
	python3 scripts/build_readme_tables.py

all: up env load-ch load-subset bench tables
	@echo "Готово. Проверьте results/summary.csv и таблицы в README.md."
