-- 改善計画T351: 派生データの世代管理・Raw→Derived系譜追跡の強化。
--
-- edge_attribute_counts/way_attribute_countsはcomputed_atしか持たず、(a) どのimport_runの
-- 内容から計算したか、(b) 「入力データが古い」のか「計算ロジックが変わった」のかを
-- DB上で区別する手段が無かった（T350のDB設計書レビューで指摘）。
--
-- source_accident_import_run_id/source_osm_import_run_idは、バッチ実行時点で
-- accident_import_runs/osm_import_runsのstatus='succeeded'な行の中でのMAX(id)を記録する
-- （＝厳密な行単位の系譜ではなく「この計算はどのデータ世代までを見ていたか」の高水位マーク。
-- accident_import_runsは年ごとに複数行が積み上がる設計のため、全年度の一覧ではなく
-- 単調増加するidの最大値を比較することで新規取込の有無を検出できれば十分という判断）。
-- 新しいimport_runが成功するたびにこの値は増加するため、記録済みの値と現在のMAX(id)を
-- 比較するだけで「再計算が必要か」を機械的に判定できるようになる。
--
-- algorithm_versionは計算ロジック自体（半径・重み付け等のパラメータ）のバージョンで、
-- 入力データが変わらなくてもロジック変更時は値が変わる（region_service.py:
-- ROAD_SURFACE_TILE_VERSIONと同じ「手動で上げる版数文字列」の考え方）。
ALTER TABLE edge_attribute_counts ADD COLUMN IF NOT EXISTS source_accident_import_run_id integer REFERENCES accident_import_runs(id) ON DELETE SET NULL;
ALTER TABLE edge_attribute_counts ADD COLUMN IF NOT EXISTS source_osm_import_run_id integer REFERENCES osm_import_runs(id) ON DELETE SET NULL;
ALTER TABLE edge_attribute_counts ADD COLUMN IF NOT EXISTS algorithm_version text;

ALTER TABLE way_attribute_counts ADD COLUMN IF NOT EXISTS source_accident_import_run_id integer REFERENCES accident_import_runs(id) ON DELETE SET NULL;
ALTER TABLE way_attribute_counts ADD COLUMN IF NOT EXISTS source_osm_import_run_id integer REFERENCES osm_import_runs(id) ON DELETE SET NULL;
ALTER TABLE way_attribute_counts ADD COLUMN IF NOT EXISTS algorithm_version text;

-- designation_attributesは1(osm_way_id, kind)に対し複数のroute_designations行が
-- ST_Unionで寄与しうる（match_designations.pyのdocstring参照）ため、単一FKでは表現できない
-- （T351が指摘した「同kindの複数route_designations行が同じWayへマッチした場合、どの行が
-- 実際にマッチしたか特定できない」問題への対応）。実際にマッチへ寄与した全route_designations.id
-- を配列で保持する。source_osm_import_run_idはosm_raw_ways側の系譜追跡（上記2テーブルと
-- 同じ高水位マーク方式）。data_version列は既にバッファ幅（アルゴリズムパラメータ）を
-- 記録済みのため、algorithm_versionは新設しない。
ALTER TABLE designation_attributes ADD COLUMN IF NOT EXISTS matched_route_designation_ids integer[];
ALTER TABLE designation_attributes ADD COLUMN IF NOT EXISTS source_osm_import_run_id integer REFERENCES osm_import_runs(id) ON DELETE SET NULL;
