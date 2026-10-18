#!/usr/bin/env bash
# Фиксация характеристик стенда. Вывод направляется в results/environment.txt.
# Определяется автоматически то, что доступно; остальное впишите руками.
set -euo pipefail

echo "# Окружение стенда"
echo "Дата замера: $(date -u +'%Y-%m-%d %H:%M:%S') UTC"
echo

echo "## Хост"
echo "ОС: $(uname -srmo 2>/dev/null || uname -a)"
if [ -r /etc/os-release ]; then . /etc/os-release; echo "Дистрибутив: ${PRETTY_NAME:-неизвестно}"; fi

echo
echo "## Процессор"
if command -v lscpu >/dev/null 2>&1; then
  lscpu | grep -E 'Model name|^CPU\(s\)|Thread|Core|Socket|MHz' || true
else
  sysctl -n machdep.cpu.brand_string 2>/dev/null || echo "lscpu недоступен — впишите модель CPU вручную"
fi

echo
echo "## Память"
if command -v free >/dev/null 2>&1; then
  free -h | head -2
else
  echo "free недоступен — впишите объём RAM вручную"
fi

echo
echo "## Накопитель (тип важен: SSD/NVMe/HDD)"
lsblk -d -o NAME,ROTA,SIZE,MODEL 2>/dev/null || echo "lsblk недоступен — впишите тип диска вручную (ROTA=0 означает SSD)"

echo
echo "## Docker"
docker --version 2>/dev/null || echo "docker недоступен"
docker compose version 2>/dev/null || true

echo
echo "## Версии СУБД (из запущенных контейнеров)"
docker exec bench-clickhouse clickhouse-client --query "SELECT version()" 2>/dev/null | sed 's/^/ClickHouse: /' || echo "ClickHouse: контейнер не запущен"
docker exec bench-postgres psql -U "${PG_USER:-bench}" -d "${PG_DB:-bench}" -tAc "show server_version" 2>/dev/null | sed 's/^/PostgreSQL: /' || echo "PostgreSQL: контейнер не запущен"
docker exec bench-mysql mysql -uroot -p"${MYSQL_ROOT_PASSWORD:-root}" -N -e "SELECT version()" 2>/dev/null | sed 's/^/MySQL: /' || echo "MySQL: контейнер не запущен"

echo
echo "## Ограничения ресурсов контейнеров"
echo "Если в docker-compose.yml не задавались limits, укажите это явно:"
echo "лимиты не выставлялись, все три СУБД работают на одной машине в равных условиях."
