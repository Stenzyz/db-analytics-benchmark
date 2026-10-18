-- ClickHouse DDL для бенчмарка на датасете NYC Taxi (yellow tripdata).
-- Схема соответствует официальной раскладке TLC yellow trip records.
-- Четыре таблицы с одинаковыми данными и разной физической организацией,
-- чтобы в экспериментах менялся ровно один параметр за раз.

-- 1. Базовая таблица: ключ сортировки по времени поездки, помесячное партиционирование.
CREATE TABLE IF NOT EXISTS trips
(
    vendor_id        LowCardinality(String),
    pickup_datetime  DateTime,
    dropoff_datetime DateTime,
    passenger_count  UInt8,
    trip_distance    Float32,
    pu_location_id   UInt16,
    do_location_id   UInt16,
    payment_type     LowCardinality(String),
    fare_amount      Float32,
    tip_amount       Float32,
    tolls_amount     Float32,
    total_amount     Float32
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(pickup_datetime)
ORDER BY (pickup_datetime, pu_location_id);

-- 2. Э2: тот же состав данных, но ключ сортировки НЕ содержит время поездки.
--    Используется для демонстрации влияния порядка колонок в ORDER BY на
--    объём прочитанных данных при фильтре по времени.
CREATE TABLE IF NOT EXISTS trips_sortkey_payment
(
    vendor_id        LowCardinality(String),
    pickup_datetime  DateTime,
    dropoff_datetime DateTime,
    passenger_count  UInt8,
    trip_distance    Float32,
    pu_location_id   UInt16,
    do_location_id   UInt16,
    payment_type     LowCardinality(String),
    fare_amount      Float32,
    tip_amount       Float32,
    tolls_amount     Float32,
    total_amount     Float32
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(pickup_datetime)
ORDER BY (payment_type);

-- 3. Э3: та же базовая организация, но БЕЗ партиционирования.
CREATE TABLE IF NOT EXISTS trips_no_partition
(
    vendor_id        LowCardinality(String),
    pickup_datetime  DateTime,
    dropoff_datetime DateTime,
    passenger_count  UInt8,
    trip_distance    Float32,
    pu_location_id   UInt16,
    do_location_id   UInt16,
    payment_type     LowCardinality(String),
    fare_amount      Float32,
    tip_amount       Float32,
    tolls_amount     Float32,
    total_amount     Float32
)
ENGINE = MergeTree
ORDER BY (pickup_datetime, pu_location_id);

-- 4. Э3 (контрпример): слишком мелкое партиционирование по дню.
--    На многолетнем периоде плодит тысячи кусков и ухудшает ситуацию.
CREATE TABLE IF NOT EXISTS trips_daily_partition
(
    vendor_id        LowCardinality(String),
    pickup_datetime  DateTime,
    dropoff_datetime DateTime,
    passenger_count  UInt8,
    trip_distance    Float32,
    pu_location_id   UInt16,
    do_location_id   UInt16,
    payment_type     LowCardinality(String),
    fare_amount      Float32,
    tip_amount       Float32,
    tolls_amount     Float32,
    total_amount     Float32
)
ENGINE = MergeTree
PARTITION BY toYYYYMMDD(pickup_datetime)
ORDER BY (pickup_datetime, pu_location_id);

-- Копии данных в остальные таблицы делаются после загрузки базовой (см. load_clickhouse.sh):
--   INSERT INTO trips_sortkey_payment  SELECT * FROM trips;
--   INSERT INTO trips_no_partition     SELECT * FROM trips;
-- Таблицу trips_daily_partition заполняйте ПОДМНОЖЕСТВОМ (например, один год),
-- иначе число партиций станет чрезмерным — в этом и состоит контрпример.
