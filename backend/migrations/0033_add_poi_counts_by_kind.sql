-- 停止要因POIの種別別カウント。既存の`stop_count`（種別を捨てた合計）と並走させ、
-- 評価軸が種別ごとの重みを持てるようにする（`domain/traffic.py: POI_COUNT_KINDS`が
-- キーの単一ソース、集計は`RoadGraphRepository`のSQLが行う）。
--
-- 種別ごとの実カラムではなくjsonbにするのは、キーを増やすときにmigration・ORM・
-- タイルSQL・材料の4箇所ではなくキー一覧の1箇所だけを触れば済むようにするため
-- （docs/tasks/T655.md「集計キー」参照）。
--
-- 適用後は precompute_edge_attribute_counts.py / precompute_way_attribute_counts.py の
-- 再実行が必須（適用しただけでは空のjsonbのまま、他のprecomputeバッチと同じ運用）。
ALTER TABLE edge_attribute_counts
    ADD COLUMN IF NOT EXISTS poi_counts jsonb NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE way_attribute_counts
    ADD COLUMN IF NOT EXISTS poi_counts jsonb NOT NULL DEFAULT '{}'::jsonb;
