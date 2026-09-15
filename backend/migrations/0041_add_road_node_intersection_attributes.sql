-- 交差点ノードの属性（信号の有無・そのノードに集まる道の最大階級）を road_nodes へ
-- 事前計算する（degree と同じ形。backend/app/batch/precompute_road_node_intersections.py）。
--
-- ターンの費用（domain/routing.py: build_turn_expanded_structure）は「進入した道より上位の
-- 道と交わる交差点」で追加の秒数を足すが、信号の有無を見ていないため、信号のある交差点でも
-- 信号待ちとは別に横断の待ちを足していた。信号での待ちは停止密度の材料が走行モデルへ運ぶ
-- （domain/traffic.py: stop_count_material_ids）ので、そこは二重になる。ターン側が足すべき
-- なのは「信号が無いのに上位の道を渡る・そこへ入る」ときの待ちで、それには交差点ノード単位で
-- 信号の有無が要る（Edge へ畳み込むと、どちらの端の信号かが失われる）。
--
-- max_highway_rank は domain/traffic.py: HIGHWAY_RANK の順位で、DB 全体から見た値。
-- 探索は読み込んだ部分グラフから同じ値を導いており、こちらはその下限を上げるためだけに使う
-- （bbox の外にはみ出した上位の道を取りこぼさない）。
--
-- 適用しただけでは has_traffic_signals=false・max_highway_rank=0 のまま
-- （degree・edge_attribute_counts と同じ運用）。既定値は「信号が無い・上位の道が無い」で、
-- どちらもバッチ実行前の挙動を今までと変えない側へ倒してある。road_edges・osm_raw_pois が
-- 変わるたび（PBF再取込時等）に再実行が要る派生データ。
ALTER TABLE road_nodes ADD COLUMN IF NOT EXISTS has_traffic_signals boolean NOT NULL DEFAULT false;
ALTER TABLE road_nodes ADD COLUMN IF NOT EXISTS max_highway_rank integer NOT NULL DEFAULT 0;
