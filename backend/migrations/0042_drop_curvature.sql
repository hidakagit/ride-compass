-- 蛇行（累積方位変化）の置き場所を落とす。road_edgesの列と、way単位の置き場だった
-- way_geometryテーブル。
--
-- この材料は「1箇所の鋭い角」と「持続する緩いカーブ」を区別できない。距離で割って
-- 平均するため、意味が正反対の2つが同じ値になる——半径30mの円がそのまま約1,900度/kmに
-- なり、自転車のために作られた周回コースが地域で最も蛇行が酷い道として採点されていた。
-- 元々は「右左折の回数をEdge単体の材料で表せない」ことの代理だったが、探索が有向区間の
-- 状態を持つようになり、ターンの費用を秒で直接数えるようになったため代理の必要も無い。
--
-- 軸・材料・算出・事前計算バッチ・タイルの焼き込みは撤去済みで、この2つを読む経路は
-- コード上に無い。way_geometryは中身が蛇行1列だけだったためテーブルごと落とす。
-- `IF EXISTS`はfresh bootstrap（`create_tables()`→`apply_pending_migrations()`）のため。
-- そこではORMの現在の定義からテーブルが作られるため、どちらも最初から存在しない。
ALTER TABLE road_edges DROP COLUMN IF EXISTS curvature_deg_per_km;
DROP TABLE IF EXISTS way_geometry;
