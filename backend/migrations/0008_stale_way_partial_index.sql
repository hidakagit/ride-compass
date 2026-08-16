-- 改善計画T68: is_split_up_to_dateはリクエストごとにbbox内の全way（GiST走査＋split_atフィルタ）
-- をスキャンしてstale行を探すが、全way freshの定常状態が大多数なのに、bboxが大きいほど
-- （ルート生成は最大60km径ループ＋マージン）走査量が線形に増える。
--
-- WHERE句の述語（is_split_up_to_dateのstale_stmt、road_graph_repository.py参照）と
-- 完全一致する部分索引を追加する。プランナがそのまま使え、定常状態では索引がほぼ空になり
-- LIMIT 1判定が即時になる（取込直後の全行staleな状態では通常GiSTと同等まで膨らむが、
-- split進行に伴い縮む）。
CREATE INDEX IF NOT EXISTS idx_osm_raw_ways_geom_stale
ON osm_raw_ways USING gist (geom)
WHERE split_at IS NULL OR split_at < updated_at;
