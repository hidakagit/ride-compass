-- 停止要因の旧集計列`stop_count`を`edge_attribute_counts`・`way_attribute_counts`から落とす。
--
-- 停止密度は停止要因POIの種別別密度（`poi_counts`、0033で追加）だけを材料にする形へ
-- 移行済みで、`stop_count`（線から15m以内にあるSTOP_POI_KINDS該当POIの総数）を読む
-- 経路はコード上に無くなった。数え方そのものが「自分が走る道の上に無い点」「1つの
-- 信号交差点を複数ノード」まで数えるもので、`poi_counts`で置き換わっている。
--
-- 列を残しても読み手が無い一方、毎回の集計バッチはこの列のためにPostGIS空間結合
-- （osm_raw_poisとの近接カウント）を1本多く実行し続ける。またUPSERTのバインド
-- パラメータ数・`EdgeMaterialTable`のpickle列数という「列数への暗黙の依存」の対象が
-- 増えたままになる。
-- `IF EXISTS`はfresh bootstrap（`create_tables()`→`apply_pending_migrations()`）のため。
-- そこではORMの現在の定義からテーブルが作られ、0010/0012の`CREATE TABLE IF NOT EXISTS`が
-- 素通りするため、この列は最初から存在しない。
ALTER TABLE edge_attribute_counts DROP COLUMN IF EXISTS stop_count;
ALTER TABLE way_attribute_counts DROP COLUMN IF EXISTS stop_count;
