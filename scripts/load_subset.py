#!/usr/bin/env python3
"""
Перенос идентичного подмножества строк из ClickHouse в PostgreSQL и MySQL для
эксперимента Э5. Корректность сравнения требует тождества данных во всех трёх
СУБД, поэтому подмножество выгружается ОДИН раз детерминированным срезом и
грузится одним и тем же файлом в обе целевые СУБД.

Зависимостей Python нет: всё делается через docker exec и клиентов внутри
контейнеров.
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUBSET_FILE = ROOT / "scripts" / "subset.tsv"

COLUMNS = (
    "vendor_id,pickup_datetime,dropoff_datetime,passenger_count,trip_distance,"
    "pu_location_id,do_location_id,payment_type,fare_amount,tip_amount,"
    "tolls_amount,total_amount"
)


def env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def load_dotenv() -> None:
    f = ROOT / ".env"
    if not f.exists():
        return
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, **kw)


def main() -> int:
    load_dotenv()

    subset_rows = env("SUBSET_ROWS", "50000000")
    ch_user, ch_pw, ch_db = env("CH_USER", "bench"), env("CH_PASSWORD", "bench"), env("CH_DB", "bench")
    pg_user, pg_db = env("PG_USER", "bench"), env("PG_DB", "bench")
    my_root, my_db = env("MYSQL_ROOT_PASSWORD", "root"), env("MYSQL_DB", "bench")

    # 1. Выгрузка детерминированного среза из ClickHouse в TSV.
    print(f"Выгружаю {subset_rows} строк из ClickHouse в {SUBSET_FILE} ...")
    # Берём самые свежие строки (DESC), чтобы в подмножество попал декабрь 2019 —
    # месяц, на котором целятся тестовые запросы Э5.
    dump_sql = (
        f"SELECT {COLUMNS} FROM trips "
        f"ORDER BY pickup_datetime DESC, pu_location_id "
        f"LIMIT {subset_rows} FORMAT TSV"
    )
    with SUBSET_FILE.open("wb") as out:
        run(
            ["docker", "exec", "-i", "bench-clickhouse", "clickhouse-client",
             "--user", ch_user, "--password", ch_pw, "--database", ch_db,
             "--max_execution_time", "0", "--query", dump_sql],
            stdout=out,
        )
    n_lines = sum(1 for _ in SUBSET_FILE.open("rb"))
    print(f"Выгружено строк: {n_lines}")

    # Зеркало ровно тех же строк в ClickHouse — чтобы Э5 сравнивал три СУБД на
    # одинаковых данных (Б1.7), а не ClickHouse на полной таблице против подмножества.
    print("Создаю trips_subset в ClickHouse (те же строки) ...")
    ch_cli = ["docker", "exec", "-i", "bench-clickhouse", "clickhouse-client",
              "--user", ch_user, "--password", ch_pw, "--database", ch_db,
              "--max_execution_time", "0", "--query"]
    run(ch_cli + ["DROP TABLE IF EXISTS trips_subset SYNC"])
    run(ch_cli + [
        "CREATE TABLE trips_subset ENGINE = MergeTree ORDER BY (pickup_datetime, pu_location_id) "
        f"AS SELECT * FROM trips ORDER BY pickup_datetime DESC LIMIT {subset_rows}"
    ])

    # 2. PostgreSQL: схема, очистка, загрузка тем же файлом, индексы, ANALYZE.
    print("Загружаю в PostgreSQL ...")
    pg_ddl = (ROOT / "sql" / "postgres" / "ddl.sql").read_text(encoding="utf-8")
    pg_exec(pg_user, pg_db, pg_ddl)
    pg_exec(pg_user, pg_db, "TRUNCATE trips;")
    # Файл внутрь контейнера коротким docker cp, затем чтение с диска — без длинной
    # потоковой трубы через docker exec (она роняет нестабильный Docker Desktop/WSL).
    run(["docker", "cp", str(SUBSET_FILE), "bench-postgres:/tmp/subset.tsv"])
    run(
        ["docker", "exec", "-i", "bench-postgres", "psql", "-U", pg_user, "-d", pg_db,
         "-c", r"\copy trips FROM '/tmp/subset.tsv' WITH (FORMAT text, DELIMITER E'\t', NULL '\N')"],
    )
    pg_exec(pg_user, pg_db,
            "CREATE INDEX IF NOT EXISTS idx_trips_pu_pickup ON trips (pu_location_id, pickup_datetime);"
            "CREATE INDEX IF NOT EXISTS idx_trips_pickup ON trips (pickup_datetime);"
            "ANALYZE trips;")
    pg_count = pg_query(pg_user, pg_db, "SELECT count(*) FROM trips;")
    print(f"PostgreSQL строк: {pg_count}")

    # 3. MySQL: схема, очистка, загрузка тем же файлом, индексы.
    print("Загружаю в MySQL ...")
    my_ddl = (ROOT / "sql" / "mysql" / "ddl.sql").read_text(encoding="utf-8")
    # Пересоздаём таблицу целиком: TRUNCATE оставляет индексы, и повторный запуск
    # падал бы на CREATE INDEX (MySQL не поддерживает IF NOT EXISTS для индексов).
    my_exec(my_root, my_db, "DROP TABLE IF EXISTS trips;")
    my_exec(my_root, my_db, my_ddl)
    # Файл внутрь контейнера, затем LOAD DATA INFILE (secure-file-priv пуст в compose).
    run(["docker", "cp", str(SUBSET_FILE), "bench-mysql:/tmp/subset.tsv"])
    my_exec(my_root, my_db,
            "LOAD DATA INFILE '/tmp/subset.tsv' INTO TABLE trips "
            "FIELDS TERMINATED BY '\\t' LINES TERMINATED BY '\\n' "
            f"({COLUMNS});")
    my_exec(my_root, my_db,
            "CREATE INDEX idx_trips_pu_pickup ON trips (pu_location_id, pickup_datetime);"
            "CREATE INDEX idx_trips_pickup ON trips (pickup_datetime);"
            "ANALYZE TABLE trips;")
    my_count = my_query(my_root, my_db, "SELECT count(*) FROM trips;")
    print(f"MySQL строк: {my_count}")

    # 4. Контроль тождества объёма (проверка Б1.7).
    print("\nСверка объёма (должны совпадать):")
    print(f"  TSV:        {n_lines}")
    print(f"  PostgreSQL: {pg_count}")
    print(f"  MySQL:      {my_count}")
    if not (str(n_lines) == str(pg_count) == str(my_count)):
        print("ВНИМАНИЕ: объёмы не совпали. Сравнение Э5 недействительно, пока не выровняете данные.")
        return 1
    print("Объёмы совпадают — данные для Э5 тождественны.")
    return 0


def pg_exec(user, db, sql):
    run(["docker", "exec", "-i", "bench-postgres", "psql", "-U", user, "-d", db, "-v", "ON_ERROR_STOP=1"],
        input=sql.encode())


def pg_query(user, db, sql):
    r = run(["docker", "exec", "-i", "bench-postgres", "psql", "-U", user, "-d", db, "-tAc", sql],
            stdout=subprocess.PIPE)
    return r.stdout.decode().strip()


def my_exec(root_pw, db, sql):
    run(["docker", "exec", "-i", "bench-mysql", "mysql", "--local-infile=1",
         "-uroot", f"-p{root_pw}", db], input=sql.encode())


def my_query(root_pw, db, sql):
    r = run(["docker", "exec", "-i", "bench-mysql", "mysql", "-N", "-uroot", f"-p{root_pw}", db, "-e", sql],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return r.stdout.decode().strip()


if __name__ == "__main__":
    sys.exit(main())
