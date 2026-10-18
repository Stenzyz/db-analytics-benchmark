#!/usr/bin/env python3
"""
Сборка таблиц результатов в README.md из results/summary.csv и
results/raw/compression.json. Каждая цифра в README таким образом берётся
напрямую из сырого файла (проверка Б1.1): руками ничего не вписывается.

Таблицы вставляются между маркерами в README:
  <!-- AUTO:compression --> ... <!-- /AUTO:compression -->
  <!-- AUTO:e2 --> ... и так далее для e3, e4, e5.
"""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUMMARY = ROOT / "results" / "summary.csv"
COMP = ROOT / "results" / "raw" / "compression.json"
README = ROOT / "README.md"

PLACEHOLDER = "_(заполняется после `make bench` → `make tables`)_"


def read_rows():
    if not SUMMARY.exists():
        return []
    with SUMMARY.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def md_table(headers, rows):
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def ch_metric_table(rows, experiment):
    sel = [r for r in rows if r["experiment"] == experiment and r["mode"] == "hot"]
    if not sel:
        return PLACEHOLDER
    body = [[r["config"], r["median_ms"], r["min_ms"], r["max_ms"],
             r["read_rows"], r["read_bytes"]] for r in sel]
    return md_table(["Конфигурация", "Медиана, мс", "Мин, мс", "Макс, мс",
                     "Прочитано строк", "Прочитано байт"], body)


def e5_table(rows):
    sel = [r for r in rows if r["experiment"] == "e5_cross_db" and r["mode"] == "hot"]
    if not sel:
        return PLACEHOLDER
    body = [[r["engine"], r["config"], r["query"], r["median_ms"], r["min_ms"],
             r["max_ms"], r["read_rows"] or "—"] for r in sel]
    return md_table(["СУБД", "Конфигурация", "Запрос", "Медиана, мс", "Мин, мс",
                     "Макс, мс", "Прочитано строк (CH)"], body)


def compression_table():
    if not COMP.exists():
        return PLACEHOLDER
    data = json.loads(COMP.read_text(encoding="utf-8"))
    out = []
    tot = data.get("table_total", "").strip()
    if tot:
        parts = tot.split("\t")
        if len(parts) >= 5:
            out.append("Таблица целиком:\n")
            out.append(md_table(["Таблица", "Строк", "Сжато", "Не сжато", "Коэффициент"],
                                [parts[:5]]))
    bycol = data.get("by_column", "").strip()
    if bycol:
        rows = [ln.split("\t") for ln in bycol.splitlines() if ln.strip()]
        out.append("\n\nПо колонкам (коэффициент сжатия, по убыванию):\n")
        out.append(md_table(["Колонка", "Сжато", "Коэффициент"], rows))
    return "\n".join(out) if out else PLACEHOLDER


def replace_marker(text, key, block):
    start, end = f"<!-- AUTO:{key} -->", f"<!-- /AUTO:{key} -->"
    if start not in text or end not in text:
        return text
    pre = text.split(start)[0]
    post = text.split(end)[1]
    return f"{pre}{start}\n{block}\n{end}{post}"


def main():
    rows = read_rows()
    text = README.read_text(encoding="utf-8")
    text = replace_marker(text, "compression", compression_table())
    text = replace_marker(text, "e2", ch_metric_table(rows, "e2_sortkey"))
    text = replace_marker(text, "e3", ch_metric_table(rows, "e3_partition"))
    text = replace_marker(text, "e4", ch_metric_table(rows, "e4_mv"))
    text = replace_marker(text, "e5", e5_table(rows))
    README.write_text(text, encoding="utf-8")
    print("README.md обновлён из summary.csv и compression.json.")
    if not rows:
        print("summary.csv пуст — сначала выполните make bench.")


if __name__ == "__main__":
    main()
