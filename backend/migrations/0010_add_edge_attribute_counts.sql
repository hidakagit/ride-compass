-- 改善計画T144: 事故密度・停止密度（タグなし交差点込み、T149）はPostGIS ST_DWithinでの
-- Edge単位空間結合が重く、現状GraphServiceが都度クエリしている。事前集計を持つ
-- edge_attribute_countsテーブルを新設する（designation_attributesと同じ「精密テーブル、
-- バッチで再計算」パターン。マテリアライズドビューではなく通常テーブル＋バッチにする理由も
-- designation_attributesと同じ: 元データ（accident_points/osm_raw_pois/road_edges）の
-- 変更のたびに明示的な再計算が必要な派生データであることを明確にするため）。
--
-- 適用後は本番でもbackend/scripts/precompute_edge_attribute_counts.pyの実行が必須
-- （適用しただけではテーブルが空のまま、designation_attributesと同じ運用）。
--
-- accident_countはdouble precision（死亡事故の重み付けSUMのため、domain/accident.py:
-- ACCIDENT_FATAL_WEIGHT参照）。stop_count/intersection_countは単純な件数のためinteger。
-- bicycle_only=trueの結果のみ保持する（road_graph_engine.pyの実際の呼び出しが常に既定値
-- bicycle_only=Trueであるため、他の値は現状使われていない）。
CREATE TABLE IF NOT EXISTS edge_attribute_counts (
    edge_id text PRIMARY KEY REFERENCES road_edges(edge_id) ON DELETE CASCADE,
    accident_count double precision NOT NULL,
    stop_count integer NOT NULL,
    intersection_count integer NOT NULL,
    computed_at timestamptz NOT NULL
);
