-- 改善計画T145b「事実はタイルに、解釈はクライアントに」: 地図タイルへ焼き込む事実
-- （事故・停止POI・交差点のカウント）のway単位事前集計。
--
-- T144のedge_attribute_counts（edge単位）はroad_edges（ルート生成時に遅延構築される
-- Road Graph）に紐づくため、地図表示に使うとルート生成済みエリアしか色が付かない
-- （dev実測: z14タイル内748way中27way=約3.6%しかカバーされない）。地図タイルの母集団で
-- あるosm_raw_ways全域（レシピ非依存の生データ層）を対象に、way単位で再集計する。
-- edge_attribute_countsは評価（ルート生成）用として並存する。
--
-- カウントの意味論はedge単位版（_ACCIDENT_COUNTS_SQL/_STOP_POI_COUNTS_SQL/
-- road_nodes.degree）と同一: 事故=半径30m内のinvolves_bicycle事故（死亡はfatal_weight倍）、
-- 停止POI=半径15m内のSTOP_POI_KINDS該当POI、交差点=半径30m内の次数3以上ノード。
-- 交差点の次数はRoad Graph非依存にするため、osm_raw_ways.node_idsの隣接関係から導出した
-- raw_intersection_nodes（次数3以上の生ノードのみ保持、バッチが全再構築）を参照する。
--
-- 適用後はbackend/app/batch/precompute_way_attribute_counts.pyの実行が必須（適用しただけ
-- ではテーブルが空のまま、edge_attribute_counts等と同じ運用）。accident_points/
-- osm_raw_pois/osm_raw_waysのいずれかが変わった場合（PBF再取込等）は再実行が必要。
CREATE TABLE raw_intersection_nodes (
    osm_node_id bigint PRIMARY KEY,
    degree integer NOT NULL,
    geom geometry(Point, 4326) NOT NULL
);
CREATE INDEX idx_raw_intersection_nodes_geom ON raw_intersection_nodes USING gist (geom);

CREATE TABLE way_attribute_counts (
    osm_way_id bigint PRIMARY KEY REFERENCES osm_raw_ways(osm_way_id) ON DELETE CASCADE,
    length_m double precision NOT NULL,
    accident_count double precision NOT NULL,
    stop_count integer NOT NULL,
    intersection_count integer NOT NULL,
    computed_at timestamptz NOT NULL
);
