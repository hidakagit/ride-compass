-- 改善計画T28（PBF初回取込の後半チャンク減速調査）で判明: osm_raw_nodes.geomのGiSTは
-- 全コードから空間検索されておらず（アクセスは常にosm_node_id指定）、取込時の逐次挿入コスト
-- と容量を消費するだけの死荷重だった（road_graph_models.py: OsmRawNodeRowのdocstring参照）。
-- spatial_index=False化と対になる、既存DB向けの冪等な削除（新規DBはそもそも作成されない）。
DROP INDEX IF EXISTS idx_osm_raw_nodes_geom;
