-- 区間単位の土地被覆クラス別割合（`way_landcover`と同じEsri×Impact Observatory由来、
-- 同じリング径・同じ算出ロジック[domain/landcover.py]、母集団だけが区間）。
-- 事前計算はbatch/precompute_edge_landcover.py。適用しただけではテーブルが空のため、
-- 実行が必須（他のprecomputeバッチと同じ運用）。
--
-- 主キーがedge_idではなく「way＋両端ノードの組」なのは、road_edgesがforward/backwardを
-- 別行で持ち、路面タイルが代表として残す行をedge_id昇順で決めるため。edge_idを鍵にすると
-- 代表の向きに行が無いときだけ値が落ちる（road_graph_repository.py:
-- _TILE_FEATURE_SOURCE_SQLがnode_lo/node_hiを出しているのと同じ理由）。この鍵ならラスタ
-- 読み出しも物理区間あたり1回で済む。
--
-- way_landcoverは撤去しない。road_edgesは取込済み範囲へpresplit_road_graph.pyが埋める
-- 派生データで、区間を持たないwayでは区間単位の行が作れないため、way単位の行が
-- 落とし先として要る。
CREATE TABLE IF NOT EXISTS edge_landcover (
    osm_way_id                bigint NOT NULL REFERENCES osm_raw_ways(osm_way_id) ON DELETE CASCADE,
    node_lo                   text NOT NULL,
    node_hi                   text NOT NULL,
    valid_pixels              integer,
    water_percent             real,
    trees_percent             real,
    flooded_veg_percent       real,
    crops_percent             real,
    built_percent             real,
    bare_percent              real,
    snow_ice_percent          real,
    rangeland_percent         real,
    data_source               text NOT NULL,
    data_version              text NOT NULL,
    computed_at               timestamptz NOT NULL,
    source_osm_import_run_id  integer REFERENCES osm_import_runs(id) ON DELETE SET NULL,
    algorithm_version         text,
    -- 「計算済み・値なし」と確定させたときのラスタ構成の指紋（way_landcoverの
    -- source_raster_setと同じ意味・同じ増分実行の判定に使う）。
    source_raster_set         text,
    -- 読み出しはwayごとにまとめて引くため、主キー索引がそのまま効く（先頭列がosm_way_id）。
    PRIMARY KEY (osm_way_id, node_lo, node_hi)
);
