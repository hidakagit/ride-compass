-- `poi_counts`の「未集計」と「集計済みで0件」を区別できるようにする。
--
-- 0033はNOT NULL DEFAULT '{}'で追加したため、集計バッチを流す前の既存行が
-- 「集計済みで0件」と区別できず、材料が0として評価される（軸が全区間で0点になり、
-- ルート選択が静かに歪む）。NULL可へ変え、NULLを「未集計＝材料は欠損」の意味にする
-- （`elevation_attributes`等が「行の有無」で同じことを表しているのと同じ流儀）。
--
-- 集計バッチは0件でも空のjsonbを明示的に書くため、実行後は`{}`＝集計済みで0件になる。
ALTER TABLE edge_attribute_counts ALTER COLUMN poi_counts DROP NOT NULL;
ALTER TABLE edge_attribute_counts ALTER COLUMN poi_counts DROP DEFAULT;
ALTER TABLE way_attribute_counts ALTER COLUMN poi_counts DROP NOT NULL;
ALTER TABLE way_attribute_counts ALTER COLUMN poi_counts DROP DEFAULT;

-- edge側は集計バッチが一度も完走していない（poi_countsが非空の行が0件）ため、
-- 既存の'{}'はすべて「未集計」を意味する。way側はバッチ完了済みで'{}'が
-- 「集計済みで0件」の正しい値のため、触らない。
UPDATE edge_attribute_counts SET poi_counts = NULL WHERE poi_counts = '{}'::jsonb;
