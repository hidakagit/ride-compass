-- 改善計画T17（最小マイグレーション機構の導入）で road_graph_repository.py: create_tables
-- 内にあった冪等ALTER/インデックス操作/バックフィルを移設したもの。すべて既に本番・開発DBへ
-- 適用済みの内容であり、この移設自体はスキーマを変更しない（内容は無変更、置き場所のみ変更）。
--
-- 新規DB（Base.metadata.create_allで作成された直後）に対しても、既存の古いDBに対しても、
-- 同じ内容が冪等に適用できる（IF NOT EXISTS / IF EXISTS を使っているため）。

-- PBF取込（Phase 1）で追加したosm_raw_ways.geom列（既存DB向けの冪等な追加）
ALTER TABLE osm_raw_ways ADD COLUMN IF NOT EXISTS geom geometry(LINESTRING,4326);
CREATE INDEX IF NOT EXISTS idx_osm_raw_ways_geom ON osm_raw_ways USING gist (geom);

-- 生データ不変時の省略パス（is_split_up_to_date）で追加したosm_raw_ways.split_at列
-- （既存DB向けの冪等な追加）
ALTER TABLE osm_raw_ways ADD COLUMN IF NOT EXISTS split_at TIMESTAMPTZ;

-- save_graphの削除ステップ（DELETE FROM road_edges WHERE osm_way_id IN (...)）が
-- インデックス無しで動いていたため追加（既存DB向けの冪等な追加）
CREATE INDEX IF NOT EXISTS idx_road_edges_osm_way_id ON road_edges USING btree (osm_way_id);

-- road_nodesへのDELETE（容量予算超過時の圧力弁・古いhighway種別のクリーンアップ等）が
-- from_node_id/to_node_id経由のFK整合性チェックでroad_edgesの全件シーケンシャル
-- スキャンを行っていたため追加（既存DB向けの冪等な追加。関東圏拡大に向けた
-- クリーンアップ作業で発覚: 35,550行の削除に27分かかった）
CREATE INDEX IF NOT EXISTS idx_road_edges_from_node_id ON road_edges USING btree (from_node_id);
CREATE INDEX IF NOT EXISTS idx_road_edges_to_node_id ON road_edges USING btree (to_node_id);

-- geom列導入前に保存された既存行のバックフィル（node_ids→osm_raw_nodesから
-- LINESTRINGを再構成）。get_way_specs_with_closureはgeomを前提とした空間検索の
-- ため、NULLのままだと旧データが閉包対象から漏れる。座標が判明しているノードが
-- 2点未満の行はNULLのまま（save_raw_ways/PBF取込と同じ意味論）。
UPDATE osm_raw_ways w
SET geom = sub.line
FROM (
    SELECT w2.osm_way_id, ST_MakeLine(n.geom ORDER BY u.ord) AS line
    FROM osm_raw_ways w2
    JOIN LATERAL unnest(w2.node_ids) WITH ORDINALITY AS u(node_id, ord) ON true
    JOIN osm_raw_nodes n ON n.osm_node_id = u.node_id
    WHERE w2.geom IS NULL
    GROUP BY w2.osm_way_id
    HAVING count(*) >= 2
) sub
WHERE w.osm_way_id = sub.osm_way_id;

-- 旧・閉包クエリ用のGINインデックス（node_ids &&）の廃止（既存DB向けの冪等な削除）。
-- geom列の空間検索への置き換えで未使用になり、実測28MB（東京都心取込時）を占めて
-- いたため、Supabaseフリープラン等の容量制約に合わせて削除する
-- （road_graph_models.py: OsmRawWayRowのdocstring参照）。
DROP INDEX IF EXISTS ix_osm_raw_ways_node_ids;
