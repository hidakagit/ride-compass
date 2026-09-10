-- `way_landcover`の「未計算」と「計算済み・値なし」を区別できるようにする。
--
-- precompute_way_landcover.pyの増分実行は`way_landcover`に行が無いwayを対象にするため、
-- ラスタ範囲外・境界またぎ・有効画素不足のway（行を作らない）は実行のたびに毎回
-- ラスタ読み込みからやり直される。結果は毎回同じ「値なし」で、全国展開でラスタが
-- 複数枚になると境界またぎのwayが増え、再実行のたびに効いてくる。
--
-- 割合8列とvalid_pixelsをNULL可へ変え、NULLを「計算済み・値なし」の意味にする
-- （0034で`poi_counts`へ同じ意味づけを与えたのと同じ流儀）。既存行はすべて値を持つため
-- 意味は変わらない。読み出しはいずれもLEFT JOINで列を参照する形のため、NULL列は
-- 「行が無い」場合と同じく欠損として扱われる。
ALTER TABLE way_landcover ALTER COLUMN valid_pixels DROP NOT NULL;
ALTER TABLE way_landcover ALTER COLUMN water_percent DROP NOT NULL;
ALTER TABLE way_landcover ALTER COLUMN trees_percent DROP NOT NULL;
ALTER TABLE way_landcover ALTER COLUMN flooded_veg_percent DROP NOT NULL;
ALTER TABLE way_landcover ALTER COLUMN crops_percent DROP NOT NULL;
ALTER TABLE way_landcover ALTER COLUMN built_percent DROP NOT NULL;
ALTER TABLE way_landcover ALTER COLUMN bare_percent DROP NOT NULL;
ALTER TABLE way_landcover ALTER COLUMN snow_ice_percent DROP NOT NULL;
ALTER TABLE way_landcover ALTER COLUMN rangeland_percent DROP NOT NULL;

-- 「値なし」と確定させたときのラスタ構成の指紋（precompute_way_landcover.py:
-- raster_set_fingerprint）。ラスタを足せば境界またぎ・範囲外のwayは値を持ちうるため、
-- 指紋が変われば増分実行が値なし行を対象に戻す。値を持つ行では意味を持たない。
ALTER TABLE way_landcover ADD COLUMN IF NOT EXISTS source_raster_set text;
