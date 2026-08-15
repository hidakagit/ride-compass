-- 外部静的データソース T50（docs/external-data-sources-review-2026-08-16.md §4.1）:
-- 警察庁 交通事故統計オープンデータの取込先テーブルを新規作成する。既存DB向けの冪等な
-- 追加（新規DBはBase.metadata.create_allで最初から持つ）。取込元がOSMではないため
-- osm_raw_pois等の既存テーブルとは分ける（rawと派生の分離を外部データにも適用する方針、
-- 同ドキュメント§4「共通方針」）。
CREATE TABLE IF NOT EXISTS accident_points (
    accident_id text PRIMARY KEY,
    occurred_year integer NOT NULL,
    fatal boolean NOT NULL,
    involves_bicycle boolean NOT NULL,
    attrs jsonb NOT NULL DEFAULT '{}'::jsonb,
    geom geometry(Point, 4326) NOT NULL,
    updated_at timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_accident_points_geom ON accident_points USING gist (geom);

CREATE TABLE IF NOT EXISTS accident_import_runs (
    id serial PRIMARY KEY,
    occurred_year integer NOT NULL,
    file_name text NOT NULL,
    status text NOT NULL,
    started_at timestamptz NOT NULL,
    finished_at timestamptz,
    accident_count bigint
);
