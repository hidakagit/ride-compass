-- 外部静的データソース T51（docs/external-data-sources-review-2026-08-16.md §4.3）:
-- 指定路線コンフレーション機構（パターンD初回実装）の取込先テーブルを新規作成する。
-- 既存DB向けの冪等な追加（新規DBはBase.metadata.create_allで最初から持つ）。
-- 取込元がOSMではないためosm_raw_ways等の既存テーブルとは分ける（accident_pointsと同じ判断）。
CREATE TABLE IF NOT EXISTS route_designations (
    id serial PRIMARY KEY,
    kind text NOT NULL,
    name text,
    pref_code text,
    attrs jsonb NOT NULL DEFAULT '{}'::jsonb,
    source text NOT NULL,
    geom geometry(LineString, 4326) NOT NULL,
    updated_at timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_route_designations_geom ON route_designations USING gist (geom);

-- Edge派生（elevation_attributes型）。1エッジが複数kind（N10かつN12）に該当しうるため
-- 複合PKにする。
CREATE TABLE IF NOT EXISTS designation_attributes (
    edge_id text NOT NULL REFERENCES road_edges(edge_id) ON DELETE CASCADE,
    kind text NOT NULL,
    matched_ratio double precision NOT NULL,
    data_version text,
    calculated_at timestamptz NOT NULL,
    PRIMARY KEY (edge_id, kind)
);

CREATE TABLE IF NOT EXISTS designation_import_runs (
    id serial PRIMARY KEY,
    kind text NOT NULL,
    source text NOT NULL,
    status text NOT NULL,
    started_at timestamptz NOT NULL,
    finished_at timestamptz,
    designation_count bigint
);
