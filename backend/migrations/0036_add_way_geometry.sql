-- Way単位の形状由来スカラー（osm_raw_ways.geomの折れ線から測る値）。
-- 現在の中身は蛇行の強さ（度/km、domain/geo.py: curvature_deg_per_km）1列で、
-- 事前計算はbatch/precompute_way_curvature.py。
--
-- road_edges.curvature_deg_per_km（Edge単位、ルート評価用）と並存する:
-- road_edgesはルート生成時に遅延構築される派生データのため、地図タイル・区間インスペクタ・
-- 軸スタジオの分布プレビューが母集団にできない（way_attribute_countsと同じ理由）。
-- 同じ材料をwayの折れ線そのものに対して測るため、wayを切り出す交差点頂点の折れも含み、
-- 値はEdge単位の延長加重平均以上になる。
--
-- 行が無い＝未計算（バッチ未実行・取込直後）、列がNULL＝算出不能（頂点1点・長さ0）。
-- 適用後はprecompute_way_curvature.pyの実行が必須（他のprecomputeバッチと同じ運用）。
CREATE TABLE IF NOT EXISTS way_geometry (
    osm_way_id                bigint PRIMARY KEY REFERENCES osm_raw_ways(osm_way_id) ON DELETE CASCADE,
    curvature_deg_per_km      double precision,
    computed_at               timestamptz NOT NULL,
    source_osm_import_run_id  integer REFERENCES osm_import_runs(id) ON DELETE SET NULL,
    algorithm_version         text
);
