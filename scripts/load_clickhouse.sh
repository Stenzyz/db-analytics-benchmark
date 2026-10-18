#!/usr/bin/env bash
# Загрузка NYC Taxi (yellow tripdata) в ClickHouse напрямую из официальных
# parquet-файлов TLC через табличную функцию url(). Грузим помесячно, пока не
# наберём CH_MAX_ROWS строк. Источник: NYC Taxi & Limousine Commission (TLC),
# https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page
#
# Важно: фактический объём определяется реально загруженными строками, а не
# заявленным. Итоговое число печатается в конце и должно попасть в README.
set -euo pipefail

cd "$(dirname "$0")/.."
[ -f .env ] && set -a && . ./.env && set +a

CH_USER="${CH_USER:-bench}"
CH_PASSWORD="${CH_PASSWORD:-bench}"
CH_DB="${CH_DB:-bench}"
CH_MAX_ROWS="${CH_MAX_ROWS:-100000000}"

# Базовый URL официальных parquet-файлов TLC.
BASE_URL="https://d37ci6vzurychx.cloudfront.net/trip-data"

# Месяцы для загрузки, от свежих к старым. Расширьте список при необходимости.
# В сумме этого с запасом хватает на 100+ млн строк.
MONTHS=$(for y in 2019 2018 2017 2016 2015; do for m in 12 11 10 09 08 07 06 05 04 03 02 01; do echo "$y-$m"; done; done)

ch() {
  docker exec -i bench-clickhouse clickhouse-client \
    --user "$CH_USER" --password "$CH_PASSWORD" --database "$CH_DB" \
    --max_execution_time 0 "$@"
}

echo "Создаю таблицы..."
ch --multiquery < sql/clickhouse/ddl.sql

current=$(ch --query "SELECT count() FROM trips")
echo "Уже загружено строк: $current"

for ym in $MONTHS; do
  if [ "$current" -ge "$CH_MAX_ROWS" ]; then
    echo "Достигнут лимит CH_MAX_ROWS=$CH_MAX_ROWS, останавливаюсь."
    break
  fi

  url="$BASE_URL/yellow_tripdata_${ym}.parquet"
  # Границы месяца для отсечения мусорных дат, встречающихся в файлах TLC.
  month_start="${ym}-01 00:00:00"
  echo "Загружаю $ym из $url ..."

  # Пропускаем недоступный месяц, не роняя весь прогон.
  ch --query "
    INSERT INTO trips
    SELECT
      toString(VendorID),
      tpep_pickup_datetime,
      tpep_dropoff_datetime,
      toUInt8OrZero(toString(passenger_count)),
      toFloat32(trip_distance),
      toUInt16OrZero(toString(PULocationID)),
      toUInt16OrZero(toString(DOLocationID)),
      toString(payment_type),
      toFloat32(fare_amount),
      toFloat32(tip_amount),
      toFloat32(tolls_amount),
      toFloat32(total_amount)
    FROM url('$url', Parquet)
    WHERE toStartOfMonth(tpep_pickup_datetime) = toStartOfMonth(toDateTime('$month_start'))
    SETTINGS input_format_parquet_skip_columns_with_unsupported_types_in_schema_inference = 1
  " || { echo "  месяц $ym пропущен (недоступен или изменилась схема)"; continue; }

  current=$(ch --query "SELECT count() FROM trips")
  echo "  всего строк: $current"
done

echo "Заполняю вспомогательные таблицы для Э2 и Э3 (копии тех же данных)..."
ch --query "TRUNCATE TABLE trips_sortkey_payment"
ch --query "INSERT INTO trips_sortkey_payment SELECT * FROM trips"
ch --query "TRUNCATE TABLE trips_no_partition"
ch --query "INSERT INTO trips_no_partition SELECT * FROM trips"

echo "Заполняю контрпример (посуточные партиции) ОДНИМ годом, чтобы показать деградацию..."
ch --query "TRUNCATE TABLE trips_daily_partition"
ch --query "
  INSERT INTO trips_daily_partition
  SELECT * FROM trips
  WHERE pickup_datetime >= '2019-01-01' AND pickup_datetime < '2020-01-01'
"

echo "Создаю витрину Э4 и наполняю её по уже загруженным данным..."
ch --multiquery < sql/clickhouse/mv.sql
ch --query "TRUNCATE TABLE daily_revenue"
ch --query "
  INSERT INTO daily_revenue
  SELECT toDate(pickup_datetime), payment_type, count(), sum(total_amount)
  FROM trips GROUP BY toDate(pickup_datetime), payment_type
"

final=$(ch --query "SELECT count() FROM trips")
echo
echo "ГОТОВО. Фактически загружено строк в trips: $final"
echo "Впишите это число в README (раздел «Датасет»)."
