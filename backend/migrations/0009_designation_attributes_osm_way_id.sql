-- 改善計画T74: designation_attributesのキーをedge_id（road_edges FK、ルート生成地点周辺のみ
-- 遅延構築）からosm_way_id（osm_raw_ways FK、関東全域自己完結）へ変更する。
-- route_designationsは全域投入済みなのに、road_edges依存のせいでルート生成履歴の無いエリアでは
-- 指定路線レイヤーが表示されない不具合（T74「遅延構築依存」）の根本対応。
--
-- designation_attributesはmatch_designations.pyが再計算する派生データ（正データはroute_designations
-- 側）のため、DROP→新スキーマで作り直して安全。適用後は本番でもmatch_designations.pyの
-- 再実行が必須（適用しただけではテーブルが空のまま）。
DROP TABLE IF EXISTS designation_attributes;

CREATE TABLE designation_attributes (
    osm_way_id bigint NOT NULL REFERENCES osm_raw_ways(osm_way_id) ON DELETE CASCADE,
    kind text NOT NULL,
    matched_ratio double precision NOT NULL,
    data_version text,
    calculated_at timestamptz NOT NULL,
    PRIMARY KEY (osm_way_id, kind)
);
