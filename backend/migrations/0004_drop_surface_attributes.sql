-- T9（surface_attributesの導出化、docs/improvement-plan.md）: Edge単位のsurfaceは
-- road_edges.osm_way_id経由でosm_raw_ways.surfaceをJOINして導出する方式へ切り替えたため、
-- 専用テーブルは不要になった。road_edges.osm_way_idのJOINにはmigration 0001で作成済みの
-- idx_road_edges_osm_way_idを使うため、新規インデックスは不要。
DROP TABLE IF EXISTS surface_attributes;
