"""Road Graph・材料の読み出し（PostGIS）。

**読み取り専用**。書き込むのは`app/batch/`の取込（`ingest_cli.py`）と派生
（`derive_cli.py`）だけで、web側は作らない。取込の範囲が決まっているぶん、ここには
「無ければ作る」経路が無い。

区間（`road_edges`）は向きを持たない1本1行で、有向の枝は探索がメモリ上で組む。DBへ
向きを伝えるのは`(osm_way_id, segment_index, forward)`の3つ組で、向きで変わる値
（方位・標高）はSQLが入れ替え・符号反転して返す。

材料の値の求め方は`domain/material_sql.py`と`domain/material_catalog.py`が持つ。ここは
式が前提にする別名（`w`/`re`/`em`/`wm`）のFROM句を組み立てるだけで、式を書かない。
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Sequence

import numpy as np
import shapely
from sqlalchemy import Float, Row, Text, bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.domain.attributes import EdgeMaterialArrays
from app.domain.graph import LeanEdge, edge_feature_key_sql, edge_key, node_key, parse_edge_feature_key
from app.domain.hard_filters import HARD_FILTER_VALUE_SQL, hard_filter_columns
from app.domain.landcover import PERCENT_CLASSES, LandcoverPercentages
from app.domain.material_catalog import (
    MATERIAL_CATALOG,
    material_array_columns,
    material_array_group,
    material_value_sql,
    stop_poi_map_group_sql,
)
from app.domain.material_sql import (
    HIGHWAY_SQL,
    LANES_COUNT_CASE_SQL,
    MAXSPEED_KMH_CASE_SQL,
    NODES_SOURCE_SQL,
    SMOOTHNESS_NORMALIZED_SQL,
    SURFACE_GOOD_CASE_SQL,
    SURFACE_NORMALIZED_SQL,
    WAYS_SOURCE_SQL,
    nodes_lookup_sql,
    ways_lookup_sql,
    ways_source_sql,
)
from app.domain.region import BoundingBox
from app.domain.road import BAD_OSM_SURFACE_TAGS, GOOD_OSM_SURFACE_TAGS
from app.domain.traffic import (
    POI_CLUSTER_EPS_M,
    POI_COUNT_KINDS,
    STOP_POI_KINDS,
    poi_count_column,
    poi_density_material_id,
    stop_kind_sql,
)
from app.infrastructure import derived_data_meta
from app.infrastructure.cache_identity import shape_digest
from app.infrastructure.derived_models import EdgeMaterialRow, WayMaterialRow
from app.infrastructure.orm_base import declared_metadata
from app.infrastructure.vector_tile import (
    ROAD_SURFACE_LAYER_NAME,
    STOP_POI_LAYER_NAME,
    TILE_EXTENT,
)

logger = logging.getLogger("ridecompass.road_graph_repository")

_CACHED_GRAPH_VERSION = "cached"

#: 1文へ載せるidの数。1配列=1パラメータなので上限ではなく転送量の都合で切る。
_ID_CHUNK_SIZE = 50_000


#: スキーマが依存する拡張。**アプリの権限では入れられない**（どちらもスーパーユーザーを
#: 要求し、trustedでもない）ため、DBを作る人が先に入れる。`raster`は面のソースの列の型で、
#: 画素の数え上げをDB側で行うために要る。
REQUIRED_EXTENSIONS = ("postgis", "postgis_raster")


async def create_tables(engine: AsyncEngine) -> None:
    """ORMが宣言するスキーマを作る（まっさらなDB向け）。

    実DBとの差は`backend/scripts/schema_gap.py`が測る。積み上げ式のmigrationは持たない
    ——正本は実DBで、ORMの宣言は「あるべき姿」である。

    拡張は**入れずに要求する**。入れるふりをすると、権限が無い環境で「機能拡張を作成する
    権限がありません」とだけ出て、何をすればよいかが伝わらない。
    """
    async with engine.begin() as conn:
        installed = set(
            (await conn.execute(text("SELECT extname FROM pg_extension"))).scalars())
        missing = [name for name in REQUIRED_EXTENSIONS if name not in installed]
        if missing:
            commands = " ".join(f"CREATE EXTENSION {name};" for name in missing)
            raise RuntimeError(
                f"このDBに拡張 {', '.join(missing)} が入っていません。"
                f"スーパーユーザーで先に実行してください: {commands}")
        await conn.run_sync(declared_metadata().create_all)


# --- 取り込んだ範囲（カバレッジ） -------------------------------------------
#
# 「この場所のデータを持っているか」は、取込の宣言そのものから決まる。マーカーの表を
# 別に持たない——持つと、取込の範囲を広げたときに2箇所を揃える必要が生まれる。
#
# `profile.target.bbox`は (min_lat, min_lon, max_lat, max_lon)。
_COVERAGE_SQL = """
    SELECT EXISTS (
        SELECT 1 FROM source_runs
        WHERE source = 'osm_way' AND status = 'succeeded'
          AND ST_Intersects(
                ST_MakeEnvelope(
                    (profile->'target'->'bbox'->>1)::double precision,
                    (profile->'target'->'bbox'->>0)::double precision,
                    (profile->'target'->'bbox'->>3)::double precision,
                    (profile->'target'->'bbox'->>2)::double precision, 4326),
                ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 4326))
    ) AS covered
"""


# --- タイルが焼く単位 ---------------------------------------------------------

#: 路面タイルが1フィーチャーとして焼く単位。**区間が読めるズームでは区間、それより引いた
#: 表示ではway丸ごと**にする。区間で焼くとgzip後の費用はz14で1.48倍・z12で1.81倍へ増える
#: 一方、z12は1pxが約38mで、交差点で切った区間は数pxにしかならず塗り分けても読めない。
EDGE_UNIT_MIN_ZOOM = 14


#: どちらの単位も`feature_key`という同じ名前で出す。フロントは`promoteId`でこれを
#: feature.idへ昇格させるだけでよく、中身がway_idか区間の鍵かを知らなくてよい。
#:
#: 空間フィルタは各枝の中に置く。外へ出すとroad_edges全件に対して走り、タイルの中身に
#: 依存しない固定コストになる。
_TILE_FEATURE_SOURCE_SQL = f"""
    SELECT
        w2.geom AS geom,
        w2.osm_way_id AS osm_way_id,
        NULL::smallint AS segment_index,
        w2.osm_way_id::text AS feature_key,
        NULL::double precision AS length_m
    FROM {WAYS_SOURCE_SQL} w2
    WHERE :z < {EDGE_UNIT_MIN_ZOOM}
      AND ST_Intersects(w2.geom, ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 4326))
    UNION ALL
    SELECT
        re.geom,
        re.osm_way_id,
        re.segment_index,
        {edge_feature_key_sql("re.osm_way_id", "re.segment_index")},
        -- 密度（件/km）の分母。way全体ではなくこの区間の長さで割る。
        re.distance_m
    FROM road_edges re
    WHERE :z >= {EDGE_UNIT_MIN_ZOOM}
      AND ST_Intersects(re.geom, ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 4326))
    UNION ALL
    -- 区間を1本も持たないway（座標が判明しているノードが2点未満のway等）は、区間単位の
    -- ズームでもway丸ごとで出す。**落とすと、その道はズームを上げたときだけ地図から
    -- 消える**——引いた表示には出ているのに拡大すると無くなる見え方は、データが無いこと
    -- よりも壊れて見える。
    SELECT
        w3.geom, w3.osm_way_id, NULL::smallint, w3.osm_way_id::text, NULL::double precision
    FROM {WAYS_SOURCE_SQL} w3
    WHERE :z >= {EDGE_UNIT_MIN_ZOOM}
      AND ST_Intersects(w3.geom, ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 4326))
      AND NOT EXISTS (SELECT 1 FROM road_edges re2 WHERE re2.osm_way_id = w3.osm_way_id)
"""


def _density_column_sql(column: str, precision: int) -> str:
    """件数をkm正規化した密度の式。

    **そのフィーチャーが表す単位から出す**。区間単位のフィーチャーは`edge_materials`の
    件数をその区間の長さで、way丸ごとのフィーチャーは`way_materials`の件数をwayの長さで
    割る——件数と長さは必ず同じ側から取る（片方だけ区間にすると、区間の件数をway全体の
    長さで割った無意味な値になる）。

    ST_AsMVTはnumeric型をtextへフォールバックするため、丸めた後にdouble precisionへ
    キャストする。0はNULLIFでプロパティ自体を省く（大多数が0のためタイルが軽くなる。
    フロントは欠損=0として扱う）。
    """
    return f"""
                        NULLIF(round((CASE
                            WHEN src.segment_index IS NOT NULL
                            THEN em.{column} * 1000.0 / NULLIF(src.length_m, 0)
                            ELSE wm.{column} * 1000.0 / NULLIF(ST_Length(w.geom::geography), 0)
                        END)::numeric, {precision}), 0)::double precision"""


#: 停止要因の種別別密度。列名は材料id（`poi_<種別>_per_km`）と同じにして対応を自明にする。
#: `POI_COUNT_KINDS`から生成するので、キーを増やしてもこの式は変わらない。
_POI_TILE_COLUMNS_SQL = "".join(
    _density_column_sql(poi_count_column(kind), 1) + f" AS {poi_density_material_id(kind)},"
    for kind in POI_COUNT_KINDS
)

#: 土地被覆の焼き込み列。材料の`tile_property`（`crops_pct`等）と同じ名前にし、クラスの
#: 宣言（`domain/landcover.py: PERCENT_CLASSES`）から組み立てる——手で並べると、クラスを
#: 1つ足したときに「材料は地図レンズを持つのに列が無い」形で静かに空になる。
_LANDCOVER_TILE_COLUMNS_SQL = (",\n").join(
    f"                        (CASE WHEN src.segment_index IS NOT NULL "
    f"THEN em.lc_{name} ELSE wm.lc_{name} END)::double precision AS {name}_pct"
    for name in (key.removesuffix("_percent") for key, _ in PERCENT_CLASSES)
)

#: 欠損を非該当として持つ真偽の材料の焼き込み列。条件は材料の値式をそのまま使い、
#: 真でなければNULLへ畳んでフィーチャーからキーを省く。値式は`w`だけを読むものに限って
#: 成り立つ——タイルのFROM句に`re`は無く、way丸ごとのフィーチャーでは`em`がNULLになる。
_BOOLEAN_TILE_COLUMNS_SQL = (",\n").join(
    f"                    CASE WHEN {spec.value_sql} THEN true END AS {spec.tile_property}"
    for spec in MATERIAL_CATALOG.values()
    if material_array_group(spec) == "boolean"
    and spec.tile_property is not None and spec.value_sql is not None
)

#: タイルが材料を引くためのJOIN。区間単位のフィーチャーだけが`em`に一致し、way丸ごとの
#: フィーチャーは`wm`側へ落ちる。
_TILE_MATERIAL_JOINS = f"""
                    JOIN LATERAL {ways_lookup_sql('src.osm_way_id')} w ON true
                    LEFT JOIN way_materials wm ON wm.osm_way_id = src.osm_way_id
                    LEFT JOIN edge_materials em
                           ON em.osm_way_id = src.osm_way_id
                          AND em.segment_index = src.segment_index
"""

# 路面タイル（MVT）をPostGIS側で丸ごと生成する。転送は完成済みタイル1個（数十KB）で済み、
# エンコードはPostGISのC実装が担う。bbox内の全way行をPythonへ転送してshapelyでdecode→
# encodeする構成だと、行転送とGILを握るCPU処理で数秒かかる。
#
# **最終値（車ストレス等）を焼かない。** タイルは全利用者で共有してキャッシュされるため、
# 判定基準を変えるたびに世界中のタイルを作り直すことになる。焼くのは材料タグと、レシピに
# 依存しない静的な事実（密度・土地被覆）だけで、最終値はフロントとルート採点がそれぞれ
# 同じ材料から計算する。
#
# カバレッジ判定も同じクエリへ畳み込み、1タイルあたりのDB往復を1回にする。CASE式は条件が
# falseの分岐を評価しないため、カバレッジ外ではMVT生成のサブクエリ自体が実行されない。
_ROAD_SURFACE_TILE_MVT_SQL = text(
    f"""
    WITH coverage AS ({_COVERAGE_SQL})
    SELECT
        coverage.covered,
        CASE WHEN coverage.covered THEN (
            SELECT ST_AsMVT(mvt.*, :layer_name, :extent, 'geom') FROM (
                SELECT
                    ST_AsMVTGeom(
                        ST_Transform(src.geom, 3857), ST_TileEnvelope(:z, :x, :y), :extent, 256, true
                    ) AS geom,
                    src.feature_key AS feature_key,
                    -- 区間インスペクタが、ポップアップに出た値と同じ行を曖昧さ無く引き
                    -- 直すための識別子。空間マッチ（半径内最近傍）だと交差点付近で別の
                    -- 道路を拾いうる。
                    w.osm_way_id AS osm_way_id,
                    -- 道路名・路線番号（表示専用）。材料の正規化はかけない——利用者へ
                    -- そのまま見せる固有名詞のため。**第三者が編集できる生値で対訳表を
                    -- 持たない**ため、埋め込む側は必ずエスケープする。
                    NULLIF(btrim(w.tags->>'name'), '') AS name,
                    NULLIF(btrim(w.tags->>'ref'), '') AS ref,
                    {SURFACE_GOOD_CASE_SQL} AS surface_good,
                    {SURFACE_NORMALIZED_SQL} AS surface,
                    {HIGHWAY_SQL} AS highway,
                    {SMOOTHNESS_NORMALIZED_SQL} AS smoothness,
{_BOOLEAN_TILE_COLUMNS_SQL},
                    -- 一方通行（表示専用）。上下線が分かれた道の片側は外す——道路としては
                    -- 双方向で、逆方向は数m隣にある。
                    CASE WHEN wm.direction <> 'both' AND NOT COALESCE(wm.divided, false)
                         THEN true END AS oneway,
                    -- ST_AsMVTはnumeric型を認識せずtextへフォールバックするため、
                    -- integerへキャストしてから焼き込む。
                    {MAXSPEED_KMH_CASE_SQL} AS maxspeed_kmh,
                    {LANES_COUNT_CASE_SQL} AS lanes_count,
                    {_density_column_sql("accident_count", 2)} AS accident_per_km,
                    {_density_column_sql("intersection_count", 1)}
                        AS intersection_per_km,{_POI_TILE_COLUMNS_SQL}
{_LANDCOVER_TILE_COLUMNS_SQL}
                FROM ({_TILE_FEATURE_SOURCE_SQL}) src
                {_TILE_MATERIAL_JOINS}
            ) mvt
            WHERE mvt.geom IS NOT NULL
        ) END AS tile
    FROM coverage
    """
).bindparams(
    bindparam("good_tags", value=sorted(GOOD_OSM_SURFACE_TAGS), type_=ARRAY(Text())),
    bindparam("bad_tags", value=sorted(BAD_OSM_SURFACE_TAGS), type_=ARRAY(Text())),
)


# 鍵→動的値配信層（風、「評価軸」グループ）。**タイルと同じソース**から鍵の一覧を引く。
# 別に組み立てると、単位の切り替わり方がタイルとずれた瞬間に鍵が噛み合わず、色が一切
# 付かない。ある道路の風の値は道路自身の向きに依らないため、方位は返さない。
# 中ほどは両端の平均で、ルートの区間の中点（`_EXTRA_MATERIAL_ARRAY_COLUMNS`の`mid_lat`/`mid_lon`）と同じ
# 決め方にする——区間単位のズームでは同じ区間が同じ予報の格子点へ寄る。
_FEATURE_MIDPOINTS_IN_TILE_SQL = text(
    f"""
    WITH coverage AS ({_COVERAGE_SQL})
    SELECT
        coverage.covered,
        CASE WHEN coverage.covered THEN (
            SELECT COALESCE(
                jsonb_object_agg(
                    src.feature_key,
                    jsonb_build_array(
                        (ST_Y(ST_StartPoint(src.geom)) + ST_Y(ST_EndPoint(src.geom))) / 2,
                        (ST_X(ST_StartPoint(src.geom)) + ST_X(ST_EndPoint(src.geom))) / 2
                    )
                ) FILTER (WHERE ST_StartPoint(src.geom) IS NOT NULL),
                '{{}}'::jsonb
            )
            FROM ({_TILE_FEATURE_SOURCE_SQL}) src
        ) END AS feature_midpoints
    FROM coverage
    """
)


# 鍵→勾配配信層。勾配は「道路自身の向き」が本質的に必要な材料（風とは異なる性質）のため、
# 鍵ごとに`(gradient_percent, road_bearing_deg)`を返す。
#
# 値は**そのフィーチャーに属する区間の、長さで重み付けた平均**。区間単位のズームでは属する
# 区間が1本なのでその区間の値そのものになり、way単位のズームではwayの全区間をならした値に
# なる。1区間の外れ値がway全体を染めることは無い。
#
# **符号付きで平均するため、結果はwayの両端の標高差と一致する**（各区間の勾配へ長さを掛ける
# と長さが約分され、標高差の総和だけが残る）。崖を下って上り返す道は打ち消し合って0%になる。
#
# 向きを揃えてから平均する。区間の勾配はジオメトリの始点→終点を正とするため、フィーチャーの
# 基準方位とのcosの符号で揃える。基準方位が定まらない閉じた道（始点＝終点）は値を返さない
# ——どちら向きに辿るかが決まらず、0%として配ると平坦と読まれる。
_FEATURE_GRADIENT_INPUTS_IN_TILE_SQL = text(
    f"""
    WITH coverage AS ({_COVERAGE_SQL})
    SELECT
        coverage.covered,
        CASE WHEN coverage.covered THEN (
            SELECT COALESCE(
                jsonb_object_agg(t.feature_key, jsonb_build_array(t.average_grade, t.bearing_deg)),
                '{{}}'::jsonb
            )
            FROM (
                SELECT
                    src.feature_key,
                    round((sum(em.average_grade
                               * sign(cos(radians(re.bearing_deg) - ref.azimuth))
                               * re.distance_m)
                           / nullif(sum(re.distance_m), 0))::numeric, 2)::double precision
                        AS average_grade,
                    degrees(ref.azimuth) AS bearing_deg
                FROM ({_TILE_FEATURE_SOURCE_SQL}) src
                CROSS JOIN LATERAL (
                    -- geographyへキャストする。geometry(4326)のままだと経度緯度を平面と
                    -- して扱った角度になり、緯度35度では真の方位と数度ずれる。
                    SELECT ST_Azimuth(ST_StartPoint(src.geom)::geography,
                                      ST_EndPoint(src.geom)::geography) AS azimuth
                ) ref
                JOIN road_edges re
                  ON re.osm_way_id = src.osm_way_id
                 AND (src.segment_index IS NULL OR re.segment_index = src.segment_index)
                JOIN edge_materials em
                  ON em.osm_way_id = re.osm_way_id AND em.segment_index = re.segment_index
                WHERE em.average_grade IS NOT NULL
                  AND re.bearing_deg IS NOT NULL
                  AND ref.azimuth IS NOT NULL
                GROUP BY src.feature_key, ref.azimuth
            ) t
        ) END AS feature_gradient_inputs
    FROM coverage
    """
)


# 停止要因POI・補給POIを1タイルへ焼き込む。種別は`node_materials.kind`（派生側の分類器が
# 付けたもの）に信号の読み替えを済ませたもので、位置は`source_features`の点。
_POI_TILE_KIND_EXPR = stop_kind_sql("nm")
_POI_TILE_GROUP_EXPR = stop_poi_map_group_sql("nm")

#: クラスタ化のためにタイルの外側も読む幅（度）。タイル境界で塊が切れると、同じ交差点が
#: 隣り合うタイルで別々の点になる。`POI_CLUSTER_EPS_M`より十分広く取る。
_POI_TILE_CLUSTER_PAD_DEG = 0.001

_POI_TILE_MVT_SQL = text(
    f"""
    WITH coverage AS ({_COVERAGE_SQL})
    SELECT
        coverage.covered,
        CASE WHEN coverage.covered THEN (
            SELECT ST_AsMVT(mvt.*, :stop_poi_layer, :extent, 'geom') FROM (
                SELECT
                    ST_AsMVTGeom(
                        ST_Transform(grouped.geom, 3857),
                        ST_TileEnvelope(:z, :x, :y), :extent, 256, true
                    ) AS geom,
                    grouped.kind AS kind
                FROM (
                    -- まとめた点の種別はどれを代表にしても凡例の同じ行に入る。
                    SELECT min(clustered.kind) AS kind,
                           ST_Centroid(ST_Collect(clustered.geom)) AS geom
                    FROM (
                        SELECT {_POI_TILE_KIND_EXPR} AS kind,
                               {_POI_TILE_GROUP_EXPR} AS map_group,
                               p.geom AS geom,
                               -- 停止要因はまとめてから出す（同じ交差点が複数の点に
                               -- ならないように）。補給POIは別々の実体なのでまとめない。
                               CASE WHEN nm.kind = ANY(:stop_kinds) THEN
                                   'c' || ST_ClusterDBSCAN(
                                       ST_Transform(p.geom, 3857),
                                       eps := :cluster_eps_m, minpoints := 1
                                   ) OVER (PARTITION BY {_POI_TILE_GROUP_EXPR})
                               ELSE 'n' || p.osm_node_id END AS cluster_key
                        FROM {NODES_SOURCE_SQL} p
                        JOIN node_materials nm ON nm.osm_node_id = p.osm_node_id
                        WHERE nm.kind IS NOT NULL
                          AND ST_Intersects(
                              p.geom,
                              ST_Expand(
                                  ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 4326),
                                  :cluster_pad_deg))
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
    bindparam("stop_poi_layer", value=STOP_POI_LAYER_NAME, type_=Text()),
    bindparam("stop_kinds", value=sorted(STOP_POI_KINDS), type_=ARRAY(Text())),
    bindparam("cluster_eps_m", value=POI_CLUSTER_EPS_M, type_=Float()),
    bindparam("cluster_pad_deg", value=_POI_TILE_CLUSTER_PAD_DEG, type_=Float()),
)


#: タイルのディスク／Redisキャッシュの鍵に入る**形の署名**。焼き込むSQLから導出するため、
#: 列や分類タグを変えれば自動的に別の鍵になる。DBの中身が作り直されたことは署名では表せず、
#: そちらは`services/tile_version_service.py`が世代の変化として扱う。
ROAD_SURFACE_TILE_SHAPE = shape_digest(_ROAD_SURFACE_TILE_MVT_SQL)
POI_TILE_SHAPE = shape_digest(_POI_TILE_MVT_SQL)


# --- way粒度の材料 -----------------------------------------------------------
#
# 材料の式は区間向けの別名を前提にする。**way1本を指すときも同じ式を使う**——wayの行から
# 同じ名前の別名を組み立てるだけで、式を2組持たない（区間インスペクタ・軸スタジオ）。
# way粒度では区間そのものの値（長さ・標高）が無いため、`re`と`em`はway単位の値かNULLを
# 返す1行にする。

#: `em`をway粒度で作るときの列。`edge_materials`と`way_materials`で同じ名前の列はway側の
#: 値を、way側に無い列（標高）はNULLを返す——列の一覧を書かず、宣言から導く。
_WAY_EM_COLUMNS = [c.name for c in EdgeMaterialRow.__table__.columns
                   if c.name not in ("osm_way_id", "segment_index", "source_run_id")]
_WAY_MATERIAL_COLUMNS = {c.name for c in WayMaterialRow.__table__.columns}
_WAY_ALIAS_EM_SQL = ", ".join(
    (f"wm2.{name} AS {name}" if name in _WAY_MATERIAL_COLUMNS
     else f"NULL::double precision AS {name}")
    for name in _WAY_EM_COLUMNS
)

_WAY_ALIAS_CLAUSES: dict[str, str] = {
    "wm": "LEFT JOIN way_materials wm ON wm.osm_way_id = w.osm_way_id",
    "re": ("CROSS JOIN LATERAL (SELECT ST_Length(w.geom::geography) AS distance_m,"
           " NULL::double precision AS bearing_deg) re"),
    "em": ("LEFT JOIN LATERAL (SELECT " + _WAY_ALIAS_EM_SQL
           + " FROM way_materials wm2 WHERE wm2.osm_way_id = w.osm_way_id) em ON true"),
}


def _way_from_clause(expressions: list[str], source: str | None = None) -> str:
    """式が参照する別名だけを含むFROM句。使わないJOINを足すと、材料1件のDISTINCTを引く
    だけの軸スタジオの値列挙まで重くなる。

    `source`は`w`をどう引くか（全件の走査・抽選付きの走査・主キーでの1件）。呼び出し側が
    決める——1件を引くのに走査を使うと、道の全件に対する総当たりになる。
    """
    needed = {alias for alias in _WAY_ALIAS_CLAUSES
              if any(f"{alias}." in expression for expression in expressions)}
    joined = "\n".join(_WAY_ALIAS_CLAUSES[name] for name in _WAY_ALIAS_CLAUSES if name in needed)
    return f"\nFROM {source or ways_source_sql()} w\n{joined}"


_WAY_MATERIAL_SELECT_SQL = ", ".join(
    f"({expr}) AS m_{name}" for name, expr in sorted(material_value_sql().items())
)


def _way_material_binds(statement):
    """材料の値式が使う配列パラメータのうち、**その文が実際に参照するものだけ**を束ねる。

    材料1件だけを引く場合（軸スタジオの値列挙）は式が使わないパラメータがあり、無条件に
    束ねるとSQLAlchemyが「その名前のパラメータは無い」と落ちる。
    """
    candidates = (
        bindparam("good_tags", value=sorted(GOOD_OSM_SURFACE_TAGS), type_=ARRAY(Text())),
        bindparam("bad_tags", value=sorted(BAD_OSM_SURFACE_TAGS), type_=ARRAY(Text())),
    )
    return statement.bindparams(*(b for b in candidates if f":{b.key}" in statement.text))


_WAY_MATERIAL_VALUES_SQL = _way_material_binds(
    text(
        f"SELECT {_WAY_MATERIAL_SELECT_SQL}"
        + _way_from_clause(list(material_value_sql().values()),
                           source=ways_lookup_sql(":osm_way_id"))
    )
)


# 軸スタジオの分布プレビューが使うway標本。材料の式は上と同じものを使い、抽選と範囲の
# 絞り込みだけを差し替える。`TABLESAMPLE SYSTEM`はページ単位の抽選で、全表走査を避けつつ
# 広い範囲から拾える（行単位のBERNOULLIや`ORDER BY random()`は数百万行の全走査になる）。
#
# 範囲を絞るときは抽選と併用しない——`TABLESAMPLE`は表全体のページから抽選するため、
# 狭い範囲を重ねると当たるページがほとんど残らず、標本が範囲の広さに関係なく数本まで落ちる。
def _sample_way_materials_sql(sampling: str, area: str):
    return _way_material_binds(
        text(
            f"SELECT ST_Length(w.geom::geography) AS length_m, {_WAY_MATERIAL_SELECT_SQL}"
            + _way_from_clause(list(material_value_sql().values()),
                               source=ways_source_sql(sampling))
            + f" WHERE w.highway IS NOT NULL {area} LIMIT :limit"
        )
    )


_SAMPLE_WAY_MATERIAL_VALUES_SQL = _sample_way_materials_sql(
    "TABLESAMPLE SYSTEM (:sample_percent)", "")
_SAMPLE_WAY_MATERIAL_VALUES_IN_BBOX_SQL = _sample_way_materials_sql(
    "", "AND w.geom && ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 4326)")

_WAY_MATERIAL_COLUMN_PREFIX = "m_"


def _material_values_from_row(row: Row) -> dict[str, object]:
    """way向けクエリの1行から材料id→値の辞書を作る。列別名は`m_<材料id>`で付けるため、
    材料の一覧をここへ書かない。"""
    return {
        key[len(_WAY_MATERIAL_COLUMN_PREFIX):]: value
        for key, value in row._mapping.items()
        if key.startswith(_WAY_MATERIAL_COLUMN_PREFIX)
    }


# --- 区間粒度の材料 -----------------------------------------------------------

#: 逆向きに辿ったときに入れ替わる／符号が反転する列。標高は地形の物理量で進行方向に
#: 依存しないため、この変換は厳密に正しい（形状点列を逆順に辿ると各区間の差分の符号が
#: すべて反転し、最大と最小も入れ替わる）。
#: 逆向きで入れ替わる語の対。列名がこの規則に従う限り、対応表を手で並べる必要がない。
_REVERSING_TOKEN_PAIRS = (("start_", "end_"), ("_gain_", "_loss_"), ("max_", "min_"))


def reversed_material_expression(name: str) -> str | None:
    """逆向きの枝でこの列へ入る式。向きで変わらない列はNone。

    対になる語を入れ替え、`_grade`で終わる量は符号を返す。形状点列を逆順に辿ると各区間の
    差分の符号がすべて反転し、最大と最小も入れ替わる。
    """
    swapped = name
    for first, second in _REVERSING_TOKEN_PAIRS:
        if first in swapped:
            swapped = swapped.replace(first, second, 1)
            break
        if second in swapped:
            swapped = swapped.replace(second, first, 1)
            break
    negated = name.endswith("_grade")
    if swapped == name and not negated:
        return None
    return ("-" if negated else "") + "m." + swapped


_REVERSED_ELEVATION_COLUMNS: dict[str, str] = {
    column.name: expression
    for column in EdgeMaterialRow.__table__.columns
    if (expression := reversed_material_expression(column.name)) is not None
}

#: 入れ替え先の列が無ければSQLは実行時に落ちる。import時に気づけるようにする。
_material_columns = {c.name for c in EdgeMaterialRow.__table__.columns}
_missing_partners = sorted(
    expression.lstrip("-").removeprefix("m.")
    for expression in _REVERSED_ELEVATION_COLUMNS.values()
    if expression.lstrip("-").removeprefix("m.") not in _material_columns
)
if _missing_partners:
    raise RuntimeError(f"逆向きの列が存在しない: {_missing_partners}")

#: 向きを解いた`em`。材料の式は向きを知らずに済み、逆向きの区間でも正しい値を読む。
_EDGE_MATERIALS_LATERAL = "LEFT JOIN LATERAL (SELECT " + ", ".join(
    (f"CASE WHEN ids.forward THEN m.{name} ELSE {_REVERSED_ELEVATION_COLUMNS[name]} END AS {name}"
     if name in _REVERSED_ELEVATION_COLUMNS else f"m.{name}")
    for name in (c.name for c in EdgeMaterialRow.__table__.columns)
) + """
    FROM edge_materials m
    WHERE m.osm_way_id = ids.osm_way_id AND m.segment_index = ids.segment_index
) em ON true"""

_HARD_FILTER_COLUMN_PREFIX = "hf_"

#: 材料ではないが、材料と同じ1回のクエリで求まるため一緒に受け取る列。
_EXTRA_MATERIAL_ARRAY_COLUMNS: dict[str, str] = {
    # 0次ハードフィルタはレジストリから列を作る。個別に書き足さない——フィルタを1つ
    # 増やしたときここが取り残されると、そのフィルタは常に「該当しない」になって黙って
    # 素通りする。
    **{f"{_HARD_FILTER_COLUMN_PREFIX}{name}": expr for name, expr in HARD_FILTER_VALUE_SQL.items()},
    "distance_m": "re.distance_m",
    # 逆向きの方位は+180°ではない。両向きぶんを列で持つ（`road_edges`）。
    "bearing_deg": "CASE WHEN ids.forward THEN re.bearing_deg ELSE re.reverse_bearing_deg END",
    "mid_lat": "(ST_Y(nf.geom) + ST_Y(nt.geom)) / 2",
    "mid_lon": "(ST_X(nf.geom) + ST_X(nt.geom)) / 2",
    "elevation_present": "em.start_elevation_m IS NOT NULL",
    "elevation_start_m": "em.start_elevation_m",
    "elevation_end_m": "em.end_elevation_m",
    "elevation_gain_m": "em.elevation_gain_m",
    "elevation_loss_m": "em.elevation_loss_m",
    "elevation_max_grade": "em.max_grade",
    "elevation_min_grade": "em.min_grade",
}

#: 列の並びは渡した3つ組の位置で固定する。**road_edgesへLEFT JOINする**——行が無い区間で
#: 配列が短くなると、以降の列と静かにずれる。
_EDGE_MATERIAL_ARRAYS_FROM = f"""
FROM unnest(CAST(:way_ids AS bigint[]), CAST(:segment_indexes AS int[]),
            CAST(:forwards AS boolean[]))
     WITH ORDINALITY AS ids(osm_way_id, segment_index, forward, ord)
LEFT JOIN road_edges re
       ON re.osm_way_id = ids.osm_way_id AND re.segment_index = ids.segment_index
LEFT JOIN LATERAL {ways_lookup_sql('ids.osm_way_id')} w ON true
LEFT JOIN way_materials wm ON wm.osm_way_id = ids.osm_way_id
{_EDGE_MATERIALS_LATERAL}
LEFT JOIN LATERAL {nodes_lookup_sql('re.from_node_id')} nf ON true
LEFT JOIN LATERAL {nodes_lookup_sql('re.to_node_id')} nt ON true
"""

#: 材料の式と付随列を1つの内包から並べる（別々に書くと`ORDER BY`がずれても気付けない）。
MATERIAL_ARRAY_COLUMN_ORDER: tuple[str, ...] = (
    *sorted(material_value_sql()),
    *_EXTRA_MATERIAL_ARRAY_COLUMNS,
)

_EDGE_MATERIAL_ARRAYS_SQL = text(
    "SELECT "
    + ", ".join(
        f"array_agg(({expr}) ORDER BY ids.ord) AS c_{name}"
        for name, expr in (
            *sorted(material_value_sql().items()),
            *_EXTRA_MATERIAL_ARRAY_COLUMNS.items(),
        )
    )
    + _EDGE_MATERIAL_ARRAYS_FROM
).bindparams(
    bindparam("good_tags", value=sorted(GOOD_OSM_SURFACE_TAGS), type_=ARRAY(Text())),
    bindparam("bad_tags", value=sorted(BAD_OSM_SURFACE_TAGS), type_=ARRAY(Text())),
)


# --- グラフの読み出し ---------------------------------------------------------
#
# 区間は向きを持たない1行で、**有向の枝は道路網全体の配列を作るとき**
# （`infrastructure/road_network_store.py`）に作る。`way_materials.direction`が逆向きの枝を
# 作ってよいかを決める。

#: 取込範囲全体の区間（向きを持たない1行）。道の行が無い区間は現れない（区間は道を切って作る
#: 派生なので、ふつうは起きない）。並びは`domain/road_network.py`の行順の前提。
_NETWORK_EDGES_SQL = text(f"""
SELECT re.osm_way_id, re.segment_index, re.from_node_id, re.to_node_id,
       w.highway, wm.direction,
       ST_XMin(re.geom) AS min_lon, ST_YMin(re.geom) AS min_lat,
       ST_XMax(re.geom) AS max_lon, ST_YMax(re.geom) AS max_lat
FROM road_edges re
JOIN LATERAL {ways_lookup_sql("re.osm_way_id")} w ON true
LEFT JOIN way_materials wm ON wm.osm_way_id = re.osm_way_id
ORDER BY re.osm_way_id, re.segment_index
""")

#: 区間の端点になりうるノード全件（`road_edges`の端点は`node_materials`に行を持つ）。
#: 座標はノードの生データから読み、生データが無いノードは現れない。
_NETWORK_NODES_SQL = text(f"""
SELECT nm.osm_node_id, ST_X(n.geom) AS longitude, ST_Y(n.geom) AS latitude,
       COALESCE(nm.has_traffic_signals, false) AS has_traffic_signals,
       COALESCE(nm.max_highway_rank, 0) AS max_highway_rank
FROM node_materials nm
JOIN LATERAL {nodes_lookup_sql("nm.osm_node_id")} n ON true
ORDER BY nm.osm_node_id
""")

#: 取込範囲全体の道路網（`infrastructure/road_network_store.py`）を作る読み出し。置き場の
#: 形の署名はここから導く——材料の式を変えると、作り直すべき置き場が別名になる。
NETWORK_SQL_SOURCES = (_NETWORK_EDGES_SQL, _NETWORK_NODES_SQL, _EDGE_MATERIAL_ARRAYS_SQL)

_EDGE_GEOMETRIES_SQL = text("""
SELECT re.osm_way_id, re.segment_index, re.from_node_id, re.to_node_id,
       re.distance_m, re.bearing_deg, re.reverse_bearing_deg,
       ST_AsBinary(re.geom) AS wkb
FROM unnest(CAST(:way_ids AS bigint[]), CAST(:segment_indexes AS int[]))
     AS ids(osm_way_id, segment_index)
JOIN road_edges re
  ON re.osm_way_id = ids.osm_way_id AND re.segment_index = ids.segment_index
""")


def _rows_to_directed_edges(rows, wanted: dict[tuple[int | None, int | None], list[bool]]
                            ) -> dict[str, LeanEdge]:
    """ジオメトリ付きの`LeanEdge`。逆向きは形状点列を逆順にする。

    `shapely.from_wkb`のバッチAPIで一括デコードする（GEOS呼び出しのループをPythonでは
    なくC側で回す）。
    """
    rows = list(rows)
    lines = shapely.from_wkb([bytes(row.wkb) for row in rows])
    edges: dict[str, LeanEdge] = {}
    for row, line in zip(rows, lines):
        points = [[lat, lon] for lon, lat in line.coords]
        for forward in wanted.get((row.osm_way_id, row.segment_index), ()):
            from_id, to_id = ((row.from_node_id, row.to_node_id) if forward
                              else (row.to_node_id, row.from_node_id))
            key = edge_key(row.osm_way_id, row.segment_index, forward)
            edges[key] = LeanEdge(
                edge_id=key, from_node_id=node_key(from_id), to_node_id=node_key(to_id),
                geometry=points if forward else list(reversed(points)),
                distance_m=row.distance_m, osm_way_id=row.osm_way_id,
                segment_index=row.segment_index, forward=forward, highway=None,
                bearing_deg=row.bearing_deg if forward else row.reverse_bearing_deg,
            )
    return edges


def _float_array(values: list) -> np.ndarray:
    return np.array([np.nan if v is None else float(v) for v in values], dtype=np.float64)


def _edge_triples(edges: list[LeanEdge]) -> tuple[list[int | None], list[int | None], list[bool]]:
    return (
        [e.osm_way_id for e in edges],
        [e.segment_index for e in edges],
        [e.forward for e in edges],
    )


def _chunked(items: list, size: int):
    for start in range(0, len(items), size):
        yield items[start:start + size]


class RoadGraphRepository:
    """道路網と材料の読み出し。1つのAsyncSessionを使う。"""

    def __init__(self, session: AsyncSession):
        self._session = session

    # --- 世代・カバレッジ ----------------------------------------------------

    async def get_derived_data_revision(self) -> int | None:
        """派生データの世代。バッチが中身を書き直すたびに進む。材料キャッシュがディスクの
        中身と突き合わせるのに使う。"""
        return await derived_data_meta.get_revision(self._session)

    async def get_accident_years(self) -> list[int]:
        """事故データの収録年。

        取込プロファイルの宣言（`rows.years`）をそのまま返す——実データの発生年を数えると、
        事故が1件も無かった年が落ちる。年数は`accident_count_per_km_year`の分母に、年そのものは
        地図の説明文に使う。どちらもここが正本で、**表示側は年を自分で持たない**。
        """
        row = await self._session.execute(text("""
            SELECT profile->'source'->'rows'->'years' AS years
            FROM source_runs
            WHERE source = 'accident' AND status = 'succeeded'
            ORDER BY run_id DESC LIMIT 1
        """))
        value = row.scalar()
        if not isinstance(value, list):
            return []
        return sorted(int(year) for year in value)

    async def get_accident_years_covered(self) -> int:
        """事故データの収録年数。`accident_count_per_km_year`の分母。"""
        return len(await self.get_accident_years())

    async def is_covered(self, bbox: BoundingBox) -> bool:
        """その範囲の生データを取り込んでいるか。判定は取込の宣言から導く。"""
        row = await self._session.execute(text(f"SELECT covered FROM ({_COVERAGE_SQL}) c"), {
            "xmin": bbox.min_longitude, "ymin": bbox.min_latitude,
            "xmax": bbox.max_longitude, "ymax": bbox.max_latitude,
        })
        return bool(row.scalar())

    # --- グラフ --------------------------------------------------------------

    async def stream_network_edges(self, chunk_size: int) -> AsyncIterator[Sequence[Row]]:
        """取込範囲全体の区間を`chunk_size`行ずつ流す（`_NETWORK_EDGES_SQL`の並び）。"""
        result = await self._session.stream(_NETWORK_EDGES_SQL)
        async for chunk in result.partitions(chunk_size):
            yield chunk

    async def stream_network_nodes(self, chunk_size: int) -> AsyncIterator[Sequence[Row]]:
        """区間の端点になりうるノード全件を`chunk_size`行ずつ流す（`osm_node_id`の昇順）。"""
        result = await self._session.stream(_NETWORK_NODES_SQL)
        async for chunk in result.partitions(chunk_size):
            yield chunk

    async def get_edges_with_geometry(self, edges: list[LeanEdge]) -> dict[str, LeanEdge]:
        """指定した枝ぶんだけ、実ジオメトリ込みの`LeanEdge`を取得する。

        探索用グラフはジオメトリを持たない。確定した経路（1候補あたり数十〜数百区間）
        だけへ絞って取り直す。
        """
        if not edges:
            return {}
        wanted: dict[tuple[int | None, int | None], list[bool]] = {}
        for edge in edges:
            wanted.setdefault((edge.osm_way_id, edge.segment_index), []).append(edge.forward)
        keys = sorted(wanted)
        result: dict[str, LeanEdge] = {}
        for chunk in _chunked(keys, _ID_CHUNK_SIZE):
            rows = (await self._session.execute(_EDGE_GEOMETRIES_SQL, {
                "way_ids": [k[0] for k in chunk],
                "segment_indexes": [k[1] for k in chunk],
            })).all()
            result.update(await asyncio.to_thread(_rows_to_directed_edges, rows, wanted))
        return result

    # --- 材料 ----------------------------------------------------------------

    async def get_edge_material_arrays(
        self, edges: list[LeanEdge], accident_years_covered: int
    ) -> EdgeMaterialArrays:
        """材料を**DB側で導出し、dtypeごとの行列として**受け取る。

        区間数に比例するPythonの仕事を持たない。**すべての列が同じ並びを持つ**必要がある
        （1つでも違うと値が列の間で静かにずれ、エラーは出ない）。並びは渡した枝の位置
        （`WITH ORDINALITY`）で固定する。
        """
        numeric_ids, boolean_ids, categorical_ids = material_array_columns()
        raw: dict[str, list] = {name: [] for name in MATERIAL_ARRAY_COLUMN_ORDER}
        for chunk in _chunked(edges, _ID_CHUNK_SIZE):
            way_ids, segment_indexes, forwards = _edge_triples(chunk)
            row = (await self._session.execute(_EDGE_MATERIAL_ARRAYS_SQL, {
                "way_ids": way_ids, "segment_indexes": segment_indexes, "forwards": forwards,
                "accident_years": accident_years_covered,
            })).one()
            for name in raw:
                raw[name].extend(getattr(row, f"c_{name}") or [])

        n = len(edges)
        hard_filter_ids = hard_filter_columns()
        hard_filter_flags = np.empty((n, len(hard_filter_ids)), dtype=bool)
        for i, name in enumerate(hard_filter_ids):
            hard_filter_flags[:, i] = [bool(v) for v in raw[f"{_HARD_FILTER_COLUMN_PREFIX}{name}"]]

        numeric_values = np.empty((n, len(numeric_ids)), dtype=np.float64)
        for i, material_id in enumerate(numeric_ids):
            numeric_values[:, i] = _float_array(raw[material_id])
        boolean_values = np.empty((n, len(boolean_ids)), dtype=bool)
        for i, material_id in enumerate(boolean_ids):
            boolean_values[:, i] = [bool(v) for v in raw[material_id]]
        categorical_values = np.empty((n, len(categorical_ids)), dtype=object)
        for i, material_id in enumerate(categorical_ids):
            categorical_values[:, i] = raw[material_id]

        return EdgeMaterialArrays(
            numeric_ids=numeric_ids, numeric_values=numeric_values,
            boolean_ids=boolean_ids, boolean_values=boolean_values,
            categorical_ids=categorical_ids, categorical_values=categorical_values,
            hard_filter_ids=hard_filter_ids, hard_filter_flags=hard_filter_flags,
            distance_m=_float_array(raw["distance_m"]),
            bearing_deg=_float_array(raw["bearing_deg"]),
            mid_lat=_float_array(raw["mid_lat"]),
            mid_lon=_float_array(raw["mid_lon"]),
            elevation_present=np.array([bool(v) for v in raw["elevation_present"]], dtype=bool),
            elevation_start_m=_float_array(raw["elevation_start_m"]),
            elevation_end_m=_float_array(raw["elevation_end_m"]),
            elevation_gain_m=_float_array(raw["elevation_gain_m"]),
            elevation_loss_m=_float_array(raw["elevation_loss_m"]),
            elevation_max_grade=_float_array(raw["elevation_max_grade"]),
            elevation_min_grade=_float_array(raw["elevation_min_grade"]),
        )

    async def get_way_material_values(
        self, osm_way_id: int, accident_years_covered: int
    ) -> dict[str, object] | None:
        """way1本ぶんの材料値（材料id→スカラー）。行が無ければNone。

        区間インスペクタが使う。式は区間の評価と同じもので、way粒度の別名を
        `_way_from_clause`が用意する。
        """
        rows = await self._session.execute(_WAY_MATERIAL_VALUES_SQL, {
            # 鍵はtextで渡す（`ways_lookup_sql`が主キーで引くため）。
            "osm_way_id": str(osm_way_id), "accident_years": accident_years_covered})
        row = rows.first()
        return None if row is None else _material_values_from_row(row)

    async def sample_way_material_values(
        self,
        accident_years_covered: int,
        sample_percent: float = 2.0,
        limit: int = 20_000,
        bbox: BoundingBox | None = None,
    ) -> list[tuple[float, dict[str, object]]]:
        """way標本を`(延長m, 材料値)`の並びで返す（軸スタジオの分布プレビュー）。

        `bbox`を渡すとその範囲内のwayだけを対象にし、抽選は使わない。軸の分布は地域で
        大きく変わるため、全域の平均だけでは市街地の偏りが見えない。
        """
        params: dict[str, object] = {"limit": limit, "accident_years": accident_years_covered}
        if bbox is None:
            statement = _SAMPLE_WAY_MATERIAL_VALUES_SQL
            params["sample_percent"] = sample_percent
        else:
            statement = _SAMPLE_WAY_MATERIAL_VALUES_IN_BBOX_SQL
            params.update(xmin=bbox.min_longitude, ymin=bbox.min_latitude,
                          xmax=bbox.max_longitude, ymax=bbox.max_latitude)
        rows = await self._session.execute(statement, params)
        return [(float(row.length_m), _material_values_from_row(row))
                for row in rows if row.length_m and row.length_m > 0]

    async def get_way_tags_by_osm_way_id(
        self, osm_way_id: int
    ) -> tuple[str | None, dict[str, str], str | None] | None:
        """osm_way_id完全一致で(highway, tags, surface)を返す。

        空間マッチ（半径内最近傍）は、交差点付近など複数の道路が近接する場所で、実際に
        クリックされたフィーチャーとは別の道路を拾いうる。フィーチャーが指す行そのものを
        引き直すことで、この不整合を構造的に防ぐ。
        """
        row = (await self._session.execute(text(f"""
            SELECT w.highway, w.tags, w.surface
            FROM {ways_lookup_sql(":osm_way_id")} w
        """), {"osm_way_id": str(osm_way_id)})).first()
        if row is None:
            return None
        return (row.highway, row.tags or {}, row.surface)

    async def get_feature_landcover(
        self, osm_way_id: int, feature_key: str | None
    ) -> LandcoverPercentages | None:
        """地図でクリックされたフィーチャー1つぶんの土地被覆（区間インスペクタの内訳）。

        **地図が塗っている値と同じ単位で読む。** 鍵から区間が特定できるときは区間の値を、
        できないときはway1本の値を使う——切り替えの規則はタイルと同じもので、揃えないと
        同じ場所で地図の色と内訳の数字が食い違う。
        """
        names = [key.removesuffix("_percent") for key in LandcoverPercentages.model_fields
                 if key.endswith("_percent")]
        columns = ["lc_valid_pixels"] + [f"lc_{name}" for name in names]
        segment = parse_edge_feature_key(feature_key) if feature_key else None
        if segment is not None and segment[0] == osm_way_id:
            row = (await self._session.execute(
                text(f"SELECT {', '.join(columns)} FROM edge_materials "
                     "WHERE osm_way_id = :osm_way_id AND segment_index = :segment_index"),
                {"osm_way_id": osm_way_id, "segment_index": segment[1]})).first()
        else:
            row = (await self._session.execute(
                text(f"SELECT {', '.join(columns)} FROM way_materials WHERE osm_way_id = :osm_way_id"),
                {"osm_way_id": osm_way_id})).first()
        if row is None or row.lc_valid_pixels is None:
            return None
        values = {name: getattr(row, f"lc_{name.removesuffix('_percent')}")
                  for name in LandcoverPercentages.model_fields if name.endswith("_percent")}
        if any(value is None for value in values.values()):
            return None
        return LandcoverPercentages(valid_pixels=row.lc_valid_pixels, **values)

    async def get_distinct_material_values(self, material_id: str) -> list[str]:
        """軸スタジオの値入力UX向け。highway/surface/smoothnessのようなオープンエンドな
        多値材料は事前に全量を静的に列挙できないため、実際にDBへ取り込まれている値を
        ここで動的取得する。未対応の`material_id`は空リスト（routerが404を判断する）。
        """
        spec = MATERIAL_CATALOG.get(material_id)
        # 値の求め方は`MaterialSpec.value_sql`が唯一持つ。ここへ式を書かない。
        # カテゴリ以外（真偽・数値）は「取りうる値の一覧」に意味が無いため対象外。
        if spec is None or spec.value_sql is None or spec.dtype != "categorical":
            return []
        column_expr = spec.value_sql
        result = await self._session.execute(
            _way_material_binds(
                text(
                    f"SELECT DISTINCT {column_expr} AS value"  # noqa: S608 カタログの宣言のみ
                    + _way_from_clause([column_expr])
                    + f" WHERE {column_expr} IS NOT NULL ORDER BY value"
                )
            )
        )
        return [row.value for row in result]

    # --- タイル --------------------------------------------------------------

    def _tile_params(self, z: int, x: int, y: int, bbox: BoundingBox) -> dict[str, object]:
        return {
            "z": z, "x": x, "y": y,
            "xmin": bbox.min_longitude, "ymin": bbox.min_latitude,
            "xmax": bbox.max_longitude, "ymax": bbox.max_latitude,
        }

    async def get_road_surface_tile_mvt(
        self, z: int, x: int, y: int, bbox: BoundingBox
    ) -> bytes | None:
        """路面レイヤーのMVTタイル1枚をPostGIS側（ST_AsMVT）で丸ごと生成して返す。

        取込範囲外はNone（呼び出し側が空タイルへのフォールバックを判断する）。範囲内で
        対象wayが1本も無い場合は空バイト列（有効な空MVT、「道路が無いことを確認済み」の
        正常応答でNoneとは区別される）。
        """
        result = await self._session.execute(_ROAD_SURFACE_TILE_MVT_SQL, {
            **self._tile_params(z, x, y, bbox),
            "layer_name": ROAD_SURFACE_LAYER_NAME, "extent": TILE_EXTENT,
        })
        covered, tile = result.one()
        if not covered:
            return None
        # 範囲内で対象0行のときST_AsMVT（集約関数）はNULLを返す。長さ0のバイト列は
        # 「featureが1つも無い有効なMVT」としてMapLibreがそのまま受理する。
        return bytes(tile) if tile is not None else b""

    async def get_poi_tile_mvt(
        self, z: int, x: int, y: int, bbox: BoundingBox
    ) -> bytes | None:
        """停止要因・補給POIレイヤーのMVTタイル1枚。契約は`get_road_surface_tile_mvt`と同じ。"""
        result = await self._session.execute(_POI_TILE_MVT_SQL, {
            **self._tile_params(z, x, y, bbox), "extent": TILE_EXTENT,
        })
        covered, tile = result.one()
        if not covered:
            return None
        return bytes(tile) if tile is not None else b""

    async def get_feature_midpoints_in_tile(
        self, z: int, x: int, y: int, bbox: BoundingBox
    ) -> dict[str, tuple[float, float]] | None:
        """動的値配信層（風）向けに、指定タイルのフィーチャーごとの中ほどの`(緯度, 経度)`を返す。
        鍵はタイルが焼いた`feature_key`と同じもの。取込範囲外はNone、範囲内0件は空。"""
        result = await self._session.execute(
            _FEATURE_MIDPOINTS_IN_TILE_SQL, self._tile_params(z, x, y, bbox))
        covered, midpoints = result.one()
        if not covered:
            return None
        return {str(key): (float(value[0]), float(value[1]))
                for key, value in (midpoints or {}).items()}

    async def get_feature_gradient_inputs_in_tile(
        self, z: int, x: int, y: int, bbox: BoundingBox
    ) -> dict[str, tuple[float, float]] | None:
        """勾配配信層向けに、フィーチャーごとの`(gradient_percent, road_bearing_deg)`を返す。
        勾配・向きのいずれかが欠損している区間は除外する。"""
        result = await self._session.execute(
            _FEATURE_GRADIENT_INPUTS_IN_TILE_SQL, self._tile_params(z, x, y, bbox))
        covered, inputs = result.one()
        if not covered:
            return None
        return {str(key): (float(value[0]), float(value[1]))
                for key, value in (inputs or {}).items()}
