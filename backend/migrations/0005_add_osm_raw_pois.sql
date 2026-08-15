-- 静的道路属性 P1（docs/static-road-attributes-plan.md）: 信号・横断歩道・一時停止・踏切の
-- node取込先テーブルを新規作成する。既存DB向けの冪等な追加（新規DBはBase.metadata.create_all
-- で最初から持つ）。osm_raw_nodesと違いgeomへGiST索引を張る（road_edgesとの空間結合に使うため）。
CREATE TABLE IF NOT EXISTS osm_raw_pois (
    osm_node_id bigint PRIMARY KEY,
    kind text NOT NULL,
    tags jsonb NOT NULL DEFAULT '{}'::jsonb,
    geom geometry(Point, 4326) NOT NULL,
    updated_at timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_osm_raw_pois_geom ON osm_raw_pois USING gist (geom);
