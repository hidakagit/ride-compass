-- Way単位の土地被覆クラス別割合（Esri×Impact Observatory Sentinel-2 10m Annual LULC由来）。
-- 道路centerlineの周囲100mリング内画素をクラスごとに集計し割合(%)へ変換したもの
-- （算出ロジックはdomain/landcover.py、事前計算はbatch/precompute_way_landcover.py）。
-- 適用後はprecompute_way_landcover.pyの実行が必須（適用しただけではテーブルが空のまま、
-- 他のprecomputeバッチと同じ運用）。
CREATE TABLE IF NOT EXISTS way_landcover (
    osm_way_id                bigint PRIMARY KEY REFERENCES osm_raw_ways(osm_way_id) ON DELETE CASCADE,
    valid_pixels              integer NOT NULL,
    water_percent             real NOT NULL,
    trees_percent             real NOT NULL,
    flooded_veg_percent       real NOT NULL,
    crops_percent             real NOT NULL,
    built_percent             real NOT NULL,
    bare_percent              real NOT NULL,
    snow_ice_percent          real NOT NULL,
    rangeland_percent         real NOT NULL,
    data_source               text NOT NULL,
    data_version              text NOT NULL,
    computed_at               timestamptz NOT NULL,
    source_osm_import_run_id  integer REFERENCES osm_import_runs(id) ON DELETE SET NULL,
    algorithm_version         text
);
