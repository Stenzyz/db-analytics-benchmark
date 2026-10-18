-- MySQL DDL (InnoDB). Состав колонок идентичен ClickHouse и PostgreSQL.

CREATE TABLE IF NOT EXISTS trips
(
    vendor_id        VARCHAR(16),
    pickup_datetime  DATETIME,
    dropoff_datetime DATETIME,
    passenger_count  TINYINT UNSIGNED,
    trip_distance    FLOAT,
    pu_location_id   SMALLINT UNSIGNED,
    do_location_id   SMALLINT UNSIGNED,
    payment_type     VARCHAR(16),
    fare_amount      FLOAT,
    tip_amount       FLOAT,
    tolls_amount     FLOAT,
    total_amount     FLOAT
) ENGINE = InnoDB;

-- Индексы создаются после загрузки:
-- CREATE INDEX idx_trips_pu_pickup ON trips (pu_location_id, pickup_datetime);
-- CREATE INDEX idx_trips_pickup    ON trips (pickup_datetime);

-- Обновление статистики:
-- ANALYZE TABLE trips;
