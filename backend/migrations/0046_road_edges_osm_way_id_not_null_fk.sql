-- 区間は`osm_raw_ways`を交差点で切って作る派生行のため、対応するwayの行が必ずある。
-- この制約をDBが持たないと、「wayの行が無い区間」という状態を読み出し側（材料の値式）が
-- 毎回吸収することになる。兄弟の派生表（way_attribute_counts・way_landcover・
-- designation_attributes等）は同じFKを既に持っており、road_edgesだけが持っていなかった。
--
-- PBF取込はwayをupsertし削除しないため、CASCADEで区間が消えるのは
-- 「wayそのものが無くなったとき」だけで、そのとき区間を残す意味は無い。
ALTER TABLE road_edges ALTER COLUMN osm_way_id SET NOT NULL;

ALTER TABLE road_edges
    ADD CONSTRAINT road_edges_osm_way_id_fkey
    FOREIGN KEY (osm_way_id) REFERENCES osm_raw_ways (osm_way_id) ON DELETE CASCADE;
