-- PostgreSQL: те же запросы, что и в ClickHouse, дословно та же логика.
-- Диапазоны дат совпадают с sql/clickhouse/queries.sql.

-- [q1_range_agg]
SELECT payment_type,
       count(*)              AS trips,
       sum(total_amount)     AS revenue,
       avg(trip_distance)    AS avg_distance
FROM trips
WHERE pickup_datetime >= '2019-12-01 00:00:00'
  AND pickup_datetime <  '2020-01-01 00:00:00'
GROUP BY payment_type
ORDER BY revenue DESC;

-- [q2_full_scan_agg]
SELECT to_char(pickup_datetime, 'YYYYMM') AS month,
       count(*)                           AS trips,
       sum(total_amount)                  AS revenue,
       avg(fare_amount)                   AS avg_fare
FROM trips
GROUP BY month
ORDER BY month;

-- [q3_selective_point]
SELECT pickup_datetime, pu_location_id, do_location_id, total_amount
FROM trips
WHERE pu_location_id = 132
  AND pickup_datetime >= '2019-12-31 00:00:00'
  AND pickup_datetime <  '2020-01-01 00:00:00'
ORDER BY pickup_datetime
LIMIT 100;

-- План выполнения с фактическими данными и буферами снимается отдельно
-- (run_benchmark.py делает это автоматически), пример вручную:
--   EXPLAIN (ANALYZE, BUFFERS) <любой из запросов выше>;
