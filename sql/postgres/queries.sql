-- MySQL: те же запросы, дословно та же логика. Диапазоны дат совпадают с другими СУБД.

-- [q1_range_agg]
SELECT payment_type,
       COUNT(*)           AS trips,
       SUM(total_amount)  AS revenue,
       AVG(trip_distance) AS avg_distance
FROM trips
WHERE pickup_datetime >= '2019-12-01 00:00:00'
  AND pickup_datetime <  '2020-01-01 00:00:00'
GROUP BY payment_type
ORDER BY revenue DESC;

-- [q2_full_scan_agg]
SELECT DATE_FORMAT(pickup_datetime, '%Y%m') AS month,
       COUNT(*)                             AS trips,
       SUM(total_amount)                    AS revenue,
       AVG(fare_amount)                     AS avg_fare
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

-- План выполнения снимается отдельно:
--   EXPLAIN <любой из запросов выше>;
--   EXPLAIN ANALYZE <запрос>;  -- MySQL 8.0.18+
