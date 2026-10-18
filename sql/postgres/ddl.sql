-- PostgreSQL DDL. Таблица идентична по составу колонок схеме ClickHouse,
-- чтобы в Э5 данные и запрос были тождественны.

CREATE TABLE IF NOT EXISTS trips
(
    vendor_id        text,
    pickup_datetime  timestamp,
    dropoff_datetime timestamp,
    passenger_count  smallint,
    trip_distance    real,
    pu_location_id   integer,
    do_location_id   integer,
    payment_type     text,
    fare_amount      real,
    tip_amount       real,
    tolls_amount     real,
    total_amount     real
);

-- Индексы создаются ПОСЛЕ загрузки данных (так быстрее и честнее для замера).
-- Для эксперимента «с индексом / без индекса» индекс создаётся и удаляется между
-- прогонами; меняется ровно один параметр.

-- Индекс под q1 (диапазон по времени) и q3 (зона + день).
-- CREATE INDEX idx_trips_pu_pickup ON trips (pu_location_id, pickup_datetime);
-- CREATE INDEX idx_trips_pickup    ON trips (pickup_datetime);

-- Удаление перед замером «без индекса»:
-- DROP INDEX IF EXISTS idx_trips_pu_pickup;
-- DROP INDEX IF EXISTS idx_trips_pickup;

-- После загрузки обязательно обновить статистику планировщика:
-- ANALYZE trips;
