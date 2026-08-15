-- 静的道路属性 P0（docs/static-road-attributes-plan.md）: osm_raw_waysへ許可リストタグの
-- jsonb列を追加する。既存DB向けの冪等な追加（新規DBはBase.metadata.create_allで
-- 最初から持つ）。容量実測（2026-08-15）で本番規模+約9MBと軽微。
ALTER TABLE osm_raw_ways ADD COLUMN IF NOT EXISTS tags jsonb NOT NULL DEFAULT '{}'::jsonb;
