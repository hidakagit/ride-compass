-- 取込runが「何を書いたか」をPOIについても残す。
--
-- 鮮度台帳は`MAX(id) WHERE status='succeeded'`を高水位として使うが、`--pois-only`の取込は
-- way・nodeを1行も書かないのに成功行を残すため、way由来の派生テーブルまで一斉に
-- 「古い」判定になっていた。way_count/node_countだけでは「POIは書いた」ことを表せず、
-- POI由来の派生テーブル（edge_attribute_countsのpoi_counts）を正しく古い判定にもできない。
--
-- 既存行はNULLのまま残す。鮮度の判定側はNULLを「不明＝書いたかもしれない」として扱う
-- （安全側＝古い判定へ倒す）ため、過去の全量取込は今までどおりPOIの高水位にもなる。
ALTER TABLE osm_import_runs ADD COLUMN IF NOT EXISTS poi_count bigint;
