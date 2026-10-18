-- Э4: предагрегация через материализованное представление.
-- Прямой аналог задачи «проектирование витрин и оптимизация тяжёлых запросов».

-- Целевая таблица витрины: суточная выручка и число поездок по типу оплаты.
-- SummingMergeTree складывает числовые меры при слиянии кусков.
CREATE TABLE IF NOT EXISTS daily_revenue
(
    day           Date,
    payment_type  LowCardinality(String),
    trips         UInt64,
    revenue       Float64
)
ENGINE = SummingMergeTree
ORDER BY (day, payment_type);

-- Материализованное представление наполняет витрину при вставке в trips.
CREATE MATERIALIZED VIEW IF NOT EXISTS daily_revenue_mv
TO daily_revenue
AS
SELECT toDate(pickup_datetime) AS day,
       payment_type,
       count()                 AS trips,
       sum(total_amount)       AS revenue
FROM trips
GROUP BY day, payment_type;

-- Важно: MV срабатывает только на НОВЫЕ вставки. Чтобы наполнить витрину по уже
-- загруженным данным, выполните разовую заливку:
--   INSERT INTO daily_revenue
--   SELECT toDate(pickup_datetime), payment_type, count(), sum(total_amount)
--   FROM trips GROUP BY day, payment_type;

-- Сами тестовые запросы Э4 (q4_raw и q4_mv) лежат в queries.sql.
