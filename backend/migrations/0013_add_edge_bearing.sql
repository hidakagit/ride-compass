-- 改善計画T218（T12 ADR Stage 0: 探索の素材事前計算化＋リーンロード）。
-- 探索時のwind評価（compute_wind_penalty）は現状、Edgeのgeometry（形状点列）の始点・終点
-- から都度bearing_between()で方位角を計算している。この計算自体は軽いが、方位角の計算
-- 「だけ」のためにgeometry（LINESTRING）をPostGISから取得・decodeする必要が生じており、
-- これが探索リクエストのボトルネック（WARM時で全体の約6割、docs/decisions/
-- t12-routing-scale.md参照）の一部になっている。bearing_degをEdge単位の永続列として
-- 持たせることで、探索フェーズ（経路選択）ではgeometryを一切取得せずに風評価が完結する
-- ようにする（domain/graph.py: DirectedEdge.bearing_deg、build_road_graph参照）。
--
-- 新規Edgeはbuild_road_graph側で算出しsave_graphが書き込むため、本カラム追加後の
-- 取込・再splitでは自動的に埋まる。既存行は本カラム追加と同時にSQLのみでバックフィルする
-- （PostGISのST_Azimuth/ST_StartPoint/ST_EndPointはgeomから直接計算できるため、
-- アプリケーション側でgeometryをdecodeするバッチは不要）。
--
-- ST_Azimuth(a, b)は「aからbを見た方位角（ラジアン、北=0、時計回り）」を返し、
-- domain/geo.py: bearing_between()と同じ定義（0=北、時計回り、0-360度）。degrees()で
-- 度へ変換する。road_edgesの各行は既にfrom_node→to_nodeの向きにgeomが格納されている
-- （domain/graph.py: build_road_graphがforward/backwardを別Edge行として持つ設計）ため、
-- 各行のST_StartPoint/ST_EndPointをそのまま使えば向きの補正は不要。
ALTER TABLE road_edges ADD COLUMN IF NOT EXISTS bearing_deg double precision;

UPDATE road_edges
SET bearing_deg = degrees(ST_Azimuth(ST_StartPoint(geom), ST_EndPoint(geom)))
WHERE bearing_deg IS NULL;
