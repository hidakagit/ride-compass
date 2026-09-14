-- 上下線が分かれた道の片側かどうか（事前計算は
-- batch/precompute_way_divided_carriageway.py）。
--
-- OSMは中央分離帯のある道路の上下線を別々のwayとして持ち、その一本ずつに oneway=yes を
-- 付ける。そのため osm_raw_ways.direction だけでは「一方通行規制の道」と「上下線が
-- 分かれた道の片側」を区別できない。後者は道路としては双方向で、逆方向は数m隣にある。
-- 一方通行レイヤーはこのテーブルで後者を外す。
--
-- way_geometry（蛇行）へ列を足さず独立したテーブルにするのは、系譜の列
-- （computed_at・source_osm_import_run_id・algorithm_version）が行単位で1組しか無く、
-- 2つのバッチが同じ行を書くと互いの系譜を上書きしてしまうため（鮮度台帳
-- derived_data_freshness.pyはこの系譜で再実行の要否を判断する）。
--
-- 行が無い＝未判定（バッチ未実行）。読む側は安全側＝falseとして扱い、従来どおり
-- direction だけで塗る（黙って何も出さないより、多く出る方を選ぶ）。
-- 適用後はprecompute_way_divided_carriageway.pyの実行が必須（他のprecomputeバッチと
-- 同じ運用）。
CREATE TABLE IF NOT EXISTS way_divided_carriageway (
    osm_way_id                bigint PRIMARY KEY REFERENCES osm_raw_ways(osm_way_id) ON DELETE CASCADE,
    divided                   boolean NOT NULL,
    computed_at               timestamptz NOT NULL,
    source_osm_import_run_id  integer REFERENCES osm_import_runs(id) ON DELETE SET NULL,
    algorithm_version         text
);
