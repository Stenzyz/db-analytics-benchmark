#!/usr/bin/env python3
"""
Прогон тестовых запросов по методике из METHODOLOGY.md.

Правила, зашитые в код:
  - первый прогон каждого запроса отбрасывается как прогрев;
  - далее не менее пяти измеряемых прогонов, считается медиана, минимум, максимум;
  - режим cold перед каждым прогоном сбрасывает кэши ClickHouse
    (SYSTEM DROP MARK CACHE, SYSTEM DROP UNCOMPRESSED CACHE);
  - сырые результаты каждого прогона сохраняются в results/raw/.

Метрики:
  - Э2/Э3/Э4 (только ClickHouse): длительность и, что важнее, прочитанные строки
    и байты из system.query_log — показывают механизм, а не только секунды.
  - Э5 (сравнение трёх СУБД): единая метрика — время по «стенным часам» клиента,
    одинаково снятая со всех трёх СУБД; дополнительно сохраняются read_rows для
    ClickHouse и планы выполнения PostgreSQL (EXPLAIN ANALYZE, BUFFERS) и MySQL.

Зависимостей Python нет: работа идёт через docker exec и клиентов в контейнерах.
"""
import argparse
import csv
import json
import os
import re
import statistics
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "results" / "raw"
SUMMARY = ROOT / "results" / "summary.csv"


def load_dotenv() -> None:
    f = ROOT / ".env"
    if not f.exists():
        return
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def env(name, default):
    return os.environ.get(name, default)


def parse_queries(path: Path) -> dict:
    """Разбор файла запросов по меткам вида [tag]."""
    text = path.read_text(encoding="utf-8")
    out, tag, buf = {}, None, []
    for line in text.splitlines():
        m = re.match(r"\s*--\s*\[([a-zA-Z0-9_]+)\]", line)
        if m:
            if tag:
                out[tag] = _clean("\n".join(buf))
            tag, buf = m.group(1), []
            continue
        if tag is not None:
            buf.append(line)
    if tag:
        out[tag] = _clean("\n".join(buf))
    return out


def _clean(block: str) -> str:
    lines = [ln for ln in block.splitlines() if not ln.strip().startswith("--")]
    sql = "\n".join(lines).strip()
    return sql.rstrip(";").strip()


# ---- ClickHouse -------------------------------------------------------------

def ch_base():
    return ["docker", "exec", "-i", "bench-clickhouse", "clickhouse-client",
            "--user", env("CH_USER", "bench"), "--password", env("CH_PASSWORD", "bench"),
            "--database", env("CH_DB", "bench"), "--max_execution_time", "0"]


def ch_run(sql, query_id=None):
    cmd = ch_base()
    if query_id:
        cmd += ["--query_id", query_id]
    cmd += ["--query", sql]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)


def ch_scalar(sql):
    r = subprocess.run(ch_base() + ["--query", sql], check=True, stdout=subprocess.PIPE)
    return r.stdout.decode().strip()


def ch_reset_caches():
    ch_run("SYSTEM DROP MARK CACHE")
    ch_run("SYSTEM DROP UNCOMPRESSED CACHE")


def ch_server_metrics(sql):
    """Выполнить запрос и вернуть серверные метрики из system.query_log."""
    qid = uuid.uuid4().hex
    ch_run(sql + "\nFORMAT Null", query_id=qid)
    ch_run("SYSTEM FLUSH LOGS")
    row = ch_scalar(
        "SELECT query_duration_ms, read_rows, read_bytes "
        "FROM system.query_log "
        f"WHERE query_id = '{qid}' AND type = 'QueryFinish' "
        "ORDER BY event_time DESC LIMIT 1"
    )
    dur, rows, bytes_ = (row.split("\t") + ["", "", ""])[:3]
    return {"duration_ms": _num(dur), "read_rows": _num(rows), "read_bytes": _num(bytes_)}


# ---- PostgreSQL -------------------------------------------------------------

def pg_base():
    return ["docker", "exec", "-i", "bench-postgres", "psql",
            "-U", env("PG_USER", "bench"), "-d", env("PG_DB", "bench"), "-tA"]


def pg_wall(sql):
    t0 = time.perf_counter()
    subprocess.run(pg_base() + ["-c", sql], check=True, stdout=subprocess.DEVNULL)
    return (time.perf_counter() - t0) * 1000.0


def pg_explain(sql):
    r = subprocess.run(pg_base() + ["-c", f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {sql}"],
                       check=True, stdout=subprocess.PIPE)
    return r.stdout.decode()


def pg_exec(sql):
    subprocess.run(pg_base() + ["-c", sql], check=True, stdout=subprocess.DEVNULL)


# ---- MySQL ------------------------------------------------------------------

def my_base():
    return ["docker", "exec", "-i", "bench-mysql", "mysql", "-N",
            "-uroot", f"-p{env('MYSQL_ROOT_PASSWORD', 'root')}", env("MYSQL_DB", "bench")]


def my_wall(sql):
    t0 = time.perf_counter()
    subprocess.run(my_base() + ["-e", sql], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return (time.perf_counter() - t0) * 1000.0


def my_explain(sql):
    r = subprocess.run(my_base() + ["-e", f"EXPLAIN ANALYZE {sql}"],
                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return r.stdout.decode()


# ---- Общее ------------------------------------------------------------------

def _num(s):
    s = (s or "").strip()
    try:
        return int(s)
    except ValueError:
        try:
            return float(s)
        except ValueError:
            return None


def measure(fn, repeats, cold_reset=None):
    """Прогрев (1, отбрасывается) + repeats измерений. Возвращает список значений."""
    if cold_reset:
        cold_reset()
    fn()  # прогрев
    vals = []
    for _ in range(repeats):
        if cold_reset:
            cold_reset()
        vals.append(fn())
    return vals


def summarize(vals):
    return {
        "median_ms": round(statistics.median(vals), 2),
        "min_ms": round(min(vals), 2),
        "max_ms": round(max(vals), 2),
        "runs": [round(v, 2) for v in vals],
    }


def save_raw(name, payload):
    (RAW / f"{name}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["hot", "cold"], default="hot")
    ap.add_argument("--repeats", type=int, default=5)
    args = ap.parse_args()
    load_dotenv()
    RAW.mkdir(parents=True, exist_ok=True)

    ch_q = parse_queries(ROOT / "sql" / "clickhouse" / "queries.sql")
    pg_q = parse_queries(ROOT / "sql" / "postgres" / "queries.sql")
    my_q = parse_queries(ROOT / "sql" / "mysql" / "queries.sql")

    rows = []  # строки для summary.csv

    def ch_timed_entry(experiment, config, table, qtag):
        sql = ch_q[qtag].replace("{table}", table) if "{table}" in ch_q[qtag] else ch_q[qtag]
        reset = ch_reset_caches if args.mode == "cold" else None
        # Прогрев + измерения; серверные метрики снимаем на каждом прогоне.
        metrics = measure(lambda: ch_server_metrics(sql)["duration_ms"], args.repeats, reset)
        last = ch_server_metrics(sql)
        s = summarize(metrics)
        name = f"ch_{experiment}_{config}_{qtag}_{args.mode}"
        save_raw(name, {"engine": "clickhouse", "experiment": experiment, "config": config,
                        "query": qtag, "mode": args.mode, "sql": sql, **s,
                        "read_rows": last["read_rows"], "read_bytes": last["read_bytes"]})
        rows.append([experiment, "clickhouse", config, qtag, args.mode, args.repeats,
                     s["median_ms"], s["min_ms"], s["max_ms"], last["read_rows"], last["read_bytes"]])
        print(f"  [ch] {experiment} {config} {qtag}: median {s['median_ms']} ms, "
              f"read_rows {last['read_rows']}")

    # --- Э1. Загрузка и сжатие (снимается один раз, в режиме hot) ---
    if args.mode == "hot":
        print("Э1. Сжатие ClickHouse ...")
        comp = ch_scalar(
            "SELECT table, sum(rows), formatReadableSize(sum(data_compressed_bytes)), "
            "formatReadableSize(sum(data_uncompressed_bytes)), "
            "round(sum(data_uncompressed_bytes)/sum(data_compressed_bytes),2) "
            "FROM system.parts WHERE active AND table='trips' GROUP BY table"
        )
        by_col = ch_scalar(
            "SELECT name, formatReadableSize(sum(data_compressed_bytes)), "
            "round(sum(data_uncompressed_bytes)/sum(data_compressed_bytes),2) AS ratio "
            "FROM system.columns WHERE table='trips' AND database=currentDatabase() "
            "GROUP BY name ORDER BY ratio DESC"
        )
        save_raw("compression", {"table_total": comp, "by_column": by_col})
        print("  сохранено в results/raw/compression.json")

    # --- Э2. Влияние ключа сортировки (запрос за ОДИН день, внутри партиции) ---
    print("Э2. Ключ сортировки ...")
    ch_timed_entry("e2_sortkey", "orderby_pickup", "trips", "q1_day_agg")
    ch_timed_entry("e2_sortkey", "orderby_payment", "trips_sortkey_payment", "q1_day_agg")

    # --- Э3. Влияние партиционирования (q1 на трёх таблицах) ---
    print("Э3. Партиционирование ...")
    ch_timed_entry("e3_partition", "by_month", "trips", "q1_range_agg")
    ch_timed_entry("e3_partition", "no_partition", "trips_no_partition", "q1_range_agg")
    ch_timed_entry("e3_partition", "by_day_counterexample", "trips_daily_partition", "q1_range_agg")

    # --- Э4. Материализованное представление ---
    print("Э4. Предагрегация через MV ...")
    ch_timed_entry("e4_mv", "raw_table", "trips", "q4_raw")
    ch_timed_entry("e4_mv", "materialized_view", "daily_revenue", "q4_mv")

    # --- Э5. Сравнение трёх СУБД (единая метрика: стенные часы) ---
    print("Э5. Сравнение PostgreSQL / ClickHouse / MySQL ...")
    for qtag in ("q1_range_agg", "q3_selective_point"):
        # ClickHouse — на том же подмножестве 2 млн строк, что PostgreSQL и MySQL (Б1.7).
        sql = ch_q[qtag].replace("{table}", "trips_subset")
        reset = ch_reset_caches if args.mode == "cold" else None
        vals = measure(lambda: _ch_wall(sql), args.repeats, reset)
        s = summarize(vals)
        rr = ch_server_metrics(sql)
        save_raw(f"e5_clickhouse_{qtag}_{args.mode}",
                 {"engine": "clickhouse", "experiment": "e5_cross_db", "query": qtag,
                  "mode": args.mode, "sql": sql, **s, "read_rows": rr["read_rows"]})
        rows.append(["e5_cross_db", "clickhouse", "trips_subset", qtag, args.mode, args.repeats,
                     s["median_ms"], s["min_ms"], s["max_ms"], rr["read_rows"], rr["read_bytes"]])
        print(f"  [ch] {qtag}: median {s['median_ms']} ms")

        # PostgreSQL (с индексом)
        vals = measure(lambda: pg_wall(pg_q[qtag]), args.repeats)
        s = summarize(vals)
        plan = pg_explain(pg_q[qtag])
        save_raw(f"e5_postgres_{qtag}_withindex_{args.mode}",
                 {"engine": "postgres", "experiment": "e5_cross_db", "query": qtag,
                  "config": "with_index", "mode": args.mode, "sql": pg_q[qtag], **s, "explain": plan})
        rows.append(["e5_cross_db", "postgres", "with_index", qtag, args.mode, args.repeats,
                     s["median_ms"], s["min_ms"], s["max_ms"], "", ""])
        print(f"  [pg] {qtag} (с индексом): median {s['median_ms']} ms")

        # MySQL
        vals = measure(lambda: my_wall(my_q[qtag]), args.repeats)
        s = summarize(vals)
        plan = my_explain(my_q[qtag])
        save_raw(f"e5_mysql_{qtag}_{args.mode}",
                 {"engine": "mysql", "experiment": "e5_cross_db", "query": qtag,
                  "mode": args.mode, "sql": my_q[qtag], **s, "explain": plan})
        rows.append(["e5_cross_db", "mysql", "default", qtag, args.mode, args.repeats,
                     s["median_ms"], s["min_ms"], s["max_ms"], "", ""])
        print(f"  [my] {qtag}: median {s['median_ms']} ms")

    # PostgreSQL без индекса (только q3, чтобы показать роль индекса на селективной выборке)
    print("Э5. PostgreSQL без индекса (q3) ...")
    pg_exec("DROP INDEX IF EXISTS idx_trips_pu_pickup; DROP INDEX IF EXISTS idx_trips_pickup;")
    try:
        vals = measure(lambda: pg_wall(pg_q["q3_selective_point"]), args.repeats)
        s = summarize(vals)
        plan = pg_explain(pg_q["q3_selective_point"])
        save_raw(f"e5_postgres_q3_selective_point_noindex_{args.mode}",
                 {"engine": "postgres", "experiment": "e5_cross_db", "query": "q3_selective_point",
                  "config": "no_index", "mode": args.mode, "sql": pg_q["q3_selective_point"], **s, "explain": plan})
        rows.append(["e5_cross_db", "postgres", "no_index", "q3_selective_point", args.mode, args.repeats,
                     s["median_ms"], s["min_ms"], s["max_ms"], "", ""])
        print(f"  [pg] q3 (без индекса): median {s['median_ms']} ms")
    finally:
        pg_exec("CREATE INDEX IF NOT EXISTS idx_trips_pu_pickup ON trips (pu_location_id, pickup_datetime);"
                "CREATE INDEX IF NOT EXISTS idx_trips_pickup ON trips (pickup_datetime); ANALYZE trips;")

    write_summary(rows)
    print(f"\nГотово. Сводка: {SUMMARY}. Сырые прогоны: {RAW}/")
    print("Теперь выполните: make tables — чтобы собрать таблицы результатов в README.")
    return 0


def _ch_wall(sql):
    t0 = time.perf_counter()
    subprocess.run(ch_base() + ["--query", sql + "\nFORMAT Null"], check=True, stdout=subprocess.DEVNULL)
    return (time.perf_counter() - t0) * 1000.0


def write_summary(rows):
    header = ["experiment", "engine", "config", "query", "mode", "repeats",
              "median_ms", "min_ms", "max_ms", "read_rows", "read_bytes"]
    existing = []
    if SUMMARY.exists():
        with SUMMARY.open(encoding="utf-8") as f:
            r = list(csv.reader(f))
            if r:
                existing = r[1:]
    # Перезаписываем строки того же (experiment,engine,config,query,mode), добавляем новые.
    key = lambda row: tuple(row[:5])
    merged = {key(r): r for r in existing}
    for row in rows:
        merged[key([str(x) for x in row])] = [str(x) for x in row]
    with SUMMARY.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        for r in sorted(merged.values()):
            w.writerow(r)


if __name__ == "__main__":
    sys.exit(main())
