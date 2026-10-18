-- Тестовые запросы ClickHouse. Каждый помечен именем в комментарии вида [q_name];
-- run_benchmark.py находит запросы по этим меткам. Диапазоны дат вынесены как
-- литералы: при другом периоде загрузки поправьте их в одном месте и в sql/postgres,
-- sql/mysql синхронно (одна переменная за раз — данные и запрос идентичны).

-- [q1_range_agg] Э1/Э2/Э3: агрегация по узкому диапазону дат с группировкой.
-- Выигрывает от ключа сортировки по времени и от помесячного партиционирования.
SELECT payment_type,
       count()               AS trips,
       sum(total_amount)     AS revenue,
       avg(trip_distance)    AS avg_distance
FROM {table}
WHERE pickup_datetime >= '2019-12-01 00:00:00'
  AND pickup_datetime <  '2020-01-01 00:00:00'
GROUP BY payment_type
ORDER BY revenue DESC;

-- [q2_full_scan_agg] Аналитика по всему объёму: помесячная выручка и средний чек.
-- Показывает преимущество колоночного чтения (читаются только нужные колонки).
SELECT toYYYYMM(pickup_datetime) AS month,
       count()                   AS trips,
       sum(total_amount)         AS revenue,
       avg(fare_amount)          AS avg_fare
FROM {table}
GROUP BY month
ORDER BY month;

-- [q3_selective_point] Контрпример: узкая выборка за один день по конкретной зоне.
-- На такой селективной точечной выборке строковое хранилище с B-tree индексом
-- (PostgreSQL) конкурентоспособно или быстрее: ClickHouse вынужден читать гранулы.
SELECT pickup_datetime, pu_location_id, do_location_id, total_amount
FROM {table}
WHERE pu_location_id = 132
  AND pickup_datetime >= '2019-12-31 00:00:00'
  AND pickup_datetime <  '2020-01-01 00:00:00'
ORDER BY pickup_datetime
LIMIT 100;

-- [q4_raw] Э4: суточная выручка по типу оплаты из ИСХОДНОЙ таблицы (тяжёлый путь).
SELECT toDate(pickup_datetime) AS day,
       payment_type,
       count()                 AS trips,
       sum(total_amount)       AS revenue
FROM trips
GROUP BY day, payment_type
ORDER BY day, payment_type;

-- [q4_mv] Э4: тот же результат из ВИТРИНЫ daily_revenue (лёгкий путь).
-- Доагрегация поверх SummingMergeTree обязательна: слияния кусков фоновые и не мгновенные.
SELECT day,
       payment_type,
       sum(trips)   AS trips,
       sum(revenue) AS revenue
FROM daily_revenue
GROUP BY day, payment_type
ORDER BY day, payment_type;

-- [q1_day_agg] Э2: агрегация за ОДИН день. Фильтр уже партиции (месяца), поэтому
-- разницу делает именно ключ сортировки (отсечение гранул), а не отсечение партиций.
SELECT payment_type,
       count()               AS trips,
       sum(total_amount)     AS revenue,
       avg(trip_distance)    AS avg_distance
FROM {table}
WHERE pickup_datetime >= '2019-12-15 00:00:00'
  AND pickup_datetime <  '2019-12-16 00:00:00'
GROUP BY payment_type
ORDER BY revenue DESC;
