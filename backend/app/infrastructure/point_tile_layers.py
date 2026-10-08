"""点データのタイル（停止要因・補給休憩のPOI・事故・立ち寄り先）のレイヤーの宣言。

点のレイヤーは`GET /api/region/point-tiles/{layer}/...`の1つの配信（`services/region_service.py:
RegionService.get_point_tile`）で配り、レイヤーごとに違うのは焼き込むSQLとsource-layer名だけである。
**点のレイヤーを足すのは、ここへ1エントリ足すことだけ**——配信・世代の表（`services/tile_version_service.py:
TILE_SHAPES`）・生成物（`region-tile-config.json`の`point_layers`）はここから組み立てる。

どのSQLも`(covered, tile)`の1行を返す。取込範囲を判定するレイヤーは`road_graph_repository.py: COVERAGE_SQL`を
読み、判定しないレイヤー（事故・立ち寄り先は対象範囲を一括で取り込むため「範囲の一部だけ取得済み」が無い）は`covered`を
常に真にする。`:layer_name`・`:extent`・タイル座標（`:z`・`:x`・`:y`・`:xmin`等）は読み出しの側
（`road_graph_repository.py: RoadGraphRepository.get_tile_mvt`）が渡す。
"""

from dataclasses import dataclass

from sqlalchemy import Float, Text, TextClause, bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY

from app.domain.accident import BICYCLE_SQL, FATAL_SQL
from app.domain.geo import degrees_covering_m
from app.domain.primary_attributes import stop_poi_map_group_sql
from app.domain.registry import TileKind
from app.domain.stop_place import StopPlaceGroup
from app.domain.traffic import POI_CLUSTER_EPS_M, STOP_POI_KINDS, stop_kind_sql
from app.infrastructure.cache_identity import shape_digest
from app.infrastructure.road_graph_repository import COVERAGE_SQL
from app.infrastructure.source_models import ACCIDENTS_SOURCE_SQL, NODES_SOURCE_SQL


@dataclass(frozen=True)
class PointTileLayer:
    #: 配信のパス・タイルの世代の系統・キャッシュのパスに入る名前。一次属性の`tile_kind`はこの名前を指す。
    name: TileKind
    #: タイルの中のレイヤー名（MapLibreのsource-layer）。空タイルもこの名前を名乗る。
    source_layer: str
    sql: TextClause

    @property
    def shape(self) -> str:
        """タイルの世代に入る形の署名。source-layer名を変えても鍵が変わる（古い名前のタイルを配らない）。"""
        return shape_digest(self.sql, self.source_layer)


# 種別は`node_materials.kind`（派生側の分類器が付けたもの）に信号の読み替えを済ませたもので、
# 位置は`source_features`の点。コンビニだけは立ち寄り先の表（`stop_places`）から足し、店の名前も添える。
_POI_KIND_EXPR = stop_kind_sql("nm")
_POI_GROUP_EXPR = stop_poi_map_group_sql("nm")

#: クラスタ化のためにタイルの外側も読む幅（度）。タイル境界で塊が切れると、同じ交差点が
#: 隣り合うタイルで別々の点になる。境目の外へ`POI_CLUSTER_EPS_M`ずつ2つ先まで連なる点を読む
#: （塊の間隔はWeb Mercatorのmで測り、その1mは地面では1m以下なので、地面のmで覆えば足りる）。
_POI_CLUSTER_PAD_DEG = degrees_covering_m(2 * POI_CLUSTER_EPS_M)

# 停止要因POI・補給POIを1タイルへ焼き込む。
_POI_TILE_MVT_SQL = text(
    f"""
    WITH coverage AS ({COVERAGE_SQL})
    SELECT
        coverage.covered,
        CASE WHEN coverage.covered THEN (
            SELECT ST_AsMVT(mvt.*, :layer_name, :extent, 'geom') FROM (
                SELECT
                    ST_AsMVTGeom(
                        ST_Transform(grouped.geom, 3857),
                        ST_TileEnvelope(:z, :x, :y), :extent, 256, true
                    ) AS geom,
                    grouped.kind AS kind,
                    grouped.name AS name
                FROM (
                    -- まとめた点の種別はどれを代表にしても凡例の同じ行に入る。
                    SELECT min(clustered.kind) AS kind,
                           min(clustered.name) AS name,
                           ST_Centroid(ST_Collect(clustered.geom)) AS geom
                    FROM (
                        SELECT {_POI_KIND_EXPR} AS kind,
                               {_POI_GROUP_EXPR} AS map_group,
                               p.geom AS geom,
                               -- 停止要因はまとめてから出す（同じ交差点が複数の点に
                               -- ならないように）。補給POIは別々の実体なのでまとめない。
                               CASE WHEN nm.kind = ANY(:stop_kinds) THEN
                                   'c' || ST_ClusterDBSCAN(
                                       ST_Transform(p.geom, 3857),
                                       eps := :cluster_eps_m, minpoints := 1
                                   ) OVER (PARTITION BY {_POI_GROUP_EXPR})
                               ELSE 'n' || p.osm_node_id END AS cluster_key,
                               NULL::text AS name
                        FROM {NODES_SOURCE_SQL} p
                        JOIN node_materials nm ON nm.osm_node_id = p.osm_node_id
                        WHERE nm.kind IS NOT NULL
                          AND ST_Intersects(
                              p.geom,
                              ST_Expand(
                                  ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 4326),
                                  :cluster_pad_deg))
                        UNION ALL
                        -- 補給POIのコンビニは立ち寄り先の群「コンビニ」の行から出す。群の値が種別の値。
                        SELECT s.place_group, s.place_group, s.geom,
                               's' || s.source || ':' || s.source_key, s.name
                        FROM stop_places s
                        WHERE s.place_group = :convenience_group
                          AND ST_Intersects(s.geom, ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 4326))
                    ) clustered
                    GROUP BY clustered.map_group, clustered.cluster_key
                ) grouped
                WHERE ST_Intersects(
                    grouped.geom, ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 4326))
            ) mvt
            WHERE mvt.geom IS NOT NULL
        ) END AS tile
    FROM coverage
    """
).bindparams(
    bindparam("stop_kinds", value=sorted(STOP_POI_KINDS), type_=ARRAY(Text())),
    bindparam("cluster_eps_m", value=POI_CLUSTER_EPS_M, type_=Float()),
    bindparam("cluster_pad_deg", value=_POI_CLUSTER_PAD_DEG, type_=Float()),
    bindparam("convenience_group", value=StopPlaceGroup.CONVENIENCE.value, type_=Text()),
)

# 事故。表示に使う値（死亡事故か・自転車が絡むか・発生年）は生データの列から都度導く。判定の
# 規則は`domain/accident.py`が持ち、集計（`derive_counts.py`）と同じものを使う。
_ACCIDENT_TILE_MVT_SQL = text(
    f"""
    SELECT
        true AS covered,
        (
            SELECT ST_AsMVT(mvt.*, :layer_name, :extent, 'geom') FROM (
                SELECT
                    ST_AsMVTGeom(
                        ST_Transform(a.geom, 3857), ST_TileEnvelope(:z, :x, :y), :extent, 256, true
                    ) AS geom,
                    {BICYCLE_SQL} AS involves_bicycle,
                    {FATAL_SQL} AS fatal,
                    a.occurred_year
                FROM {ACCIDENTS_SOURCE_SQL} a
                WHERE ST_Intersects(a.geom, ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 4326))
            ) mvt
            WHERE mvt.geom IS NOT NULL
        ) AS tile
    """
)

# 立ち寄り先。群へ入れ、近くの同じ店をまとめた後の表（`batch/derive_stop_places.py`）をそのまま出す。
_STOP_PLACE_TILE_MVT_SQL = text(
    """
    SELECT
        true AS covered,
        (
            SELECT ST_AsMVT(mvt.*, :layer_name, :extent, 'geom') FROM (
                SELECT
                    ST_AsMVTGeom(
                        ST_Transform(s.geom, 3857), ST_TileEnvelope(:z, :x, :y), :extent, 256, true
                    ) AS geom,
                    s.place_group AS "group",
                    s.confidence,
                    s.name
                FROM stop_places s
                -- 群「コンビニ」は補給の点のタイル（`poi`）が出す。
                WHERE s.place_group <> :convenience_group
                  AND ST_Intersects(s.geom, ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 4326))
            ) mvt
            WHERE mvt.geom IS NOT NULL
        ) AS tile
    """
).bindparams(bindparam("convenience_group", value=StopPlaceGroup.CONVENIENCE.value, type_=Text()))

#: 名前→点のレイヤー。
POINT_TILE_LAYERS: dict[str, PointTileLayer] = {
    layer.name: layer
    for layer in (
        PointTileLayer(name="poi", source_layer="stop_poi", sql=_POI_TILE_MVT_SQL),
        PointTileLayer(name="accident", source_layer="accidents", sql=_ACCIDENT_TILE_MVT_SQL),
        PointTileLayer(name="stop_place", source_layer="stop_places", sql=_STOP_PLACE_TILE_MVT_SQL),
    )
}
