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
import re
from collections.abc import AsyncIterator, Iterable, Sequence

import numpy as np
import shapely
from sqlalchemy import Column, Row, TextClause, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.domain.attributes import AVERAGE_GRADE_DECIMALS, CategoricalColumn, EdgeMaterialArrays
from app.domain.graph import LeanEdge, edge_feature_key_sql, edge_key, node_key, parse_edge_feature_key
from app.domain.hard_filters import HARD_FILTER_VALUE_SQL, hard_filter_columns
from app.domain.landcover import LandcoverPercentages, landcover_key
from app.domain.material_catalog import (
    GRADIENT_PERCENT,
    MATERIAL_CATALOG,
    material_array_columns,
    material_tile_columns,
    material_value_sql,
    tile_unscaled_sql_params,
)
from app.domain.material_sql import length_weighted_mean_sql
from app.infrastructure.source_models import (
    WAYS_SOURCE_SQL,
    Source,
    latest_succeeded_run_sql,
    nodes_lookup_sql,
    ways_lookup_sql,
    ways_source_sql,
)
from app.domain.region import EDGE_UNIT_MIN_ZOOM, BoundingBox
from app.infrastructure import derived_data_meta
from app.infrastructure.cache_identity import shape_digest
from app.infrastructure.derived_models import RoadEdgeRow
from app.infrastructure.orm_base import DERIVED_KEY, declared_metadata
from app.infrastructure.vector_tile import (
    ROAD_FEATURE_PROPERTIES,
    ROAD_SURFACE_LAYER_NAME,
    TILE_EXTENT,
)

logger = logging.getLogger("ridecompass.road_graph_repository")

#: 1文へ載せるidの数。1配列=1パラメータなので上限ではなく転送量の都合で切る。
ID_CHUNK_SIZE = 50_000


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
        installed: set[str] = set(
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
# 手元の道路データは、成功した最新の道路の取込のもの——取込はソースのパーティションを入れ替え、派生も
# 最新のrunから作る。範囲はそのrunが記録した宣言（`profile.target.bbox`、(min_lat, min_lon, max_lat, max_lon)）。
# 住所の区画の派生の段（`batch/derive_addresses.py`）も、町字をこの範囲で選ぶ。道路を取り込んでいなければ0行。
INGESTED_BBOX_SQL = f"""
    SELECT
        (profile->'target'->'bbox'->>0)::double precision AS min_lat,
        (profile->'target'->'bbox'->>1)::double precision AS min_lon,
        (profile->'target'->'bbox'->>2)::double precision AS max_lat,
        (profile->'target'->'bbox'->>3)::double precision AS max_lon
    FROM {latest_succeeded_run_sql(Source.OSM_WAY)} latest
"""

#: 要求タイルが取込範囲に入るか（`covered`）。範囲を判定するタイルのSQL（点のタイルは
#: `point_tile_layers.py`）は`WITH coverage AS (...)`で読む。
COVERAGE_SQL = f"""
    SELECT EXISTS (
        SELECT 1 FROM ({INGESTED_BBOX_SQL}) ingested
        WHERE ST_Intersects(
            ST_MakeEnvelope(ingested.min_lon, ingested.min_lat, ingested.max_lon, ingested.max_lat, 4326),
            ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 4326))
    ) AS covered
"""


# --- 材料の表の結び方 ---------------------------------------------------------
#
# 材料の式は、区間に付く値を別名`em`、道1本に付く値を別名`wm`の列として読む（`domain/material_sql.py`）。
# その2つの別名を与えるFROM句は`material_from_clause`だけが組み立てる。どの列がどの表にあるかは宣言から
# 導き、式が読む列を持つ表だけを主キーで結ぶ。区間の表か道の表かは主キーの列で決まる。

_EDGE_KEY = ("osm_way_id", "segment_index")
_WAY_KEY = ("osm_way_id",)


def _material_columns(key: tuple[str, ...]) -> dict[str, Column]:
    """主キーの列が`key`の派生の表（区間の形の`road_edges`を除く）の、鍵でない列。名前→列。

    同じ名前の列を2つの表が持つと、別名の列がどちらの表から来るかが決まらないので送出する。
    """
    columns: dict[str, Column] = {}
    for table in declared_metadata().sorted_tables:
        if (not table.info.get(DERIVED_KEY) or table is RoadEdgeRow.__table__
                or tuple(column.name for column in table.primary_key.columns) != key):
            continue
        for column in table.columns:
            if column.primary_key:
                continue
            if column.name in columns:
                raise RuntimeError(
                    f"材料の表 {columns[column.name].table.name} と {table.name} が同じ列 {column.name} を持つ")
            columns[column.name] = column
    return columns


_EDGE_MATERIAL_COLUMNS = _material_columns(_EDGE_KEY)
_WAY_MATERIAL_COLUMNS = _material_columns(_WAY_KEY)

#: 逆向きで入れ替わる語の対。列名がこの規則に従う限り、対応表を手で並べる必要がない。
_REVERSING_TOKEN_PAIRS = (("start_", "end_"), ("_gain_", "_loss_"))


def reversed_material_expression(name: str) -> str | None:
    """逆向きの枝でこの列へ入る式（入れ替える相手の列を別名`m`で読む）。向きで変わらない列はNone。

    対になる語を入れ替え、`_grade`で終わる量は符号を返す。標高は地形の物理量で進行方向に依存しないため、
    この変換は厳密に正しい（形状点列を逆順に辿ると各区間の差分の符号がすべて反転する）。
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


#: 区間の列→逆向きで読む相手の列と、符号を返すか。
_REVERSED_EDGE_COLUMNS: dict[str, tuple[str, bool]] = {
    name: (expression.lstrip("-").removeprefix("m."), expression.startswith("-"))
    for name in _EDGE_MATERIAL_COLUMNS
    if (expression := reversed_material_expression(name)) is not None
}

#: 入れ替え先の列が無ければSQLは実行時に落ちる。import時に気づけるようにする。
_missing_partners = sorted(partner for partner, _ in _REVERSED_EDGE_COLUMNS.values()
                           if partner not in _EDGE_MATERIAL_COLUMNS)
if _missing_partners:
    raise RuntimeError(f"逆向きの列が存在しない: {_missing_partners}")

_MATERIAL_REFERENCE = re.compile(r"(?<![\w.])(em|wm)\.(\w+)")


def material_from_clause(
    expressions: Iterable[str], way_id: str, segment_index: str | None = None, *,
    forward: str | None = None, way_when_no_segment: bool = False,
) -> str:
    """`expressions`が読む`em`・`wm`の列を与えるJOINの並び。読む列を持つ表だけを、主キーで`way_id`
    （と`segment_index`）の式へ外部結合する。呼び出し側はFROM句の行の後ろへそのまま続ける。

    `em`は、`segment_index`を渡せば区間の値、Noneなら道1本の値（区間の表と同じ名前の道の列。道に無い列はNULL）。
    `way_when_no_segment`は、`segment_index`の式がNULLの行を道1本の値で読む（区間と道丸ごとが混ざるタイル）。
    `forward`（真なら順方向）を渡すと、`em`の向きで変わる列を逆向きの行で入れ替え・符号反転する。

    式が宣言に無い列を読めば送出する——SQLの実行まで気づかないと、その経路の読み出しが材料ぶん丸ごと落ちる。
    """
    names: dict[str, set[str]] = {"em": set(), "wm": set()}
    for expression in expressions:
        for alias, name in _MATERIAL_REFERENCE.findall(expression):
            if name not in (_EDGE_MATERIAL_COLUMNS if alias == "em" else _WAY_MATERIAL_COLUMNS):
                raise ValueError(f"材料の式が宣言に無い列を読む: {alias}.{name}")
            names[alias].add(name)

    tables: set = set()

    def read(column: Column) -> str:
        tables.add(column.table)
        return f"t_{column.table.name}.{column.name}"

    def edge_value(name: str) -> str:
        value = read(_EDGE_MATERIAL_COLUMNS[name])
        if forward is None or name not in _REVERSED_EDGE_COLUMNS:
            return value
        partner, negated = _REVERSED_EDGE_COLUMNS[name]
        reverse = ("-" if negated else "") + read(_EDGE_MATERIAL_COLUMNS[partner])
        return f"CASE WHEN {forward} THEN {value} ELSE {reverse} END"

    def way_value(name: str) -> str | None:
        column = _WAY_MATERIAL_COLUMNS.get(name)
        return None if column is None else read(column)

    selects: dict[str, list[str]] = {"em": [], "wm": []}
    for name in sorted(names["em"]):
        if segment_index is None:
            value = way_value(name) or (
                f"CAST(NULL AS {_EDGE_MATERIAL_COLUMNS[name].type.compile(dialect=postgresql.dialect())})")
        elif way_when_no_segment:
            way = way_value(name)
            value = (f"CASE WHEN {segment_index} IS NOT NULL THEN {edge_value(name)}"
                     + (f" ELSE {way}" if way is not None else "") + " END")
        else:
            value = edge_value(name)
        selects["em"].append(f"{value} AS {name}")
    for name in sorted(names["wm"]):
        selects["wm"].append(f"{read(_WAY_MATERIAL_COLUMNS[name])} AS {name}")

    lines = []
    for table in sorted(tables, key=lambda table: table.name):
        on = f"t_{table.name}.osm_way_id = {way_id}"
        if tuple(column.name for column in table.primary_key.columns) == _EDGE_KEY:
            on += f" AND t_{table.name}.segment_index = {segment_index}"
        lines.append(f"LEFT JOIN {table.name} t_{table.name} ON {on}")
    lines += [f"CROSS JOIN LATERAL (SELECT {', '.join(select)}) {alias}"
              for alias, select in selects.items() if select]
    return "".join(f"\n{line}" for line in lines) + "\n"


# --- タイルが焼く単位 ---------------------------------------------------------

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
    -- 区間を1本も持たないway（同じ位置に点が重なり長さ0の区間しか作れないway等）は、区間単位の
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


#: 材料の焼き込み列。`tile_property`を持つ全材料について、値式から組んだ式を並べる
#: （`domain/material_catalog.py: material_tile_columns`）。列を手で書くと、地図と評価が別々の求め方になる。
_MATERIAL_TILE_COLUMNS_SQL = ",\n".join(
    f"                    {expression} AS {tile_property}"
    for tile_property, expression in material_tile_columns().items()
)

#: タイルが材料を引くためのJOIN。値式が読む別名（`w`・`wm`・`em`・`re`）をフィーチャーの単位で与え、
#: 区間でもway丸ごとでも同じ値式を使う。`em`は区間単位のフィーチャーなら区間の値、way丸ごとなら道1本の値で、
#: 件数と長さ（`re`）は必ず同じ側から取る——片方だけ区間にすると、区間の件数をway全体の長さで割った
#: 無意味な値になる。`re`は長さだけを持ち、way丸ごとのフィーチャーはwayの長さ（0はNULL）にする。
_TILE_MATERIAL_JOINS = f"""
                    JOIN LATERAL {ways_lookup_sql('src.osm_way_id')} w ON true
                    {material_from_clause(material_tile_columns().values(), 'src.osm_way_id',
                                          'src.segment_index', way_when_no_segment=True)}
                    CROSS JOIN LATERAL (
                        -- `OFFSET 0`は外へ畳ませないためのもの——畳まれると`re.distance_m`を読む
                        -- 値式ごとに道の長さを測り直す。
                        SELECT CASE WHEN src.segment_index IS NOT NULL THEN src.length_m
                                    ELSE NULLIF(ST_Length(w.geom::geography), 0) END AS distance_m
                        OFFSET 0
                    ) re
"""

# 路面タイル（MVT）をPostGIS側で丸ごと生成する。転送は完成済みタイル1個（数十KB）で済み、
# エンコードはPostGISのC実装が担う。bbox内の全way行をPythonへ転送してshapelyでdecode→
# encodeする構成だと、行転送とGILを握るCPU処理で数秒かかる。
#
# **最終値（軸の得点）を焼かない。** タイルは全利用者で共有してキャッシュされるため、
# 判定基準を変えるたびに世界中のタイルを作り直すことになる。焼くのは材料の値（レシピに
# 依存しない静的な事実）だけで、最終値はフロントとルート採点がそれぞれ同じ材料から計算する。
# 実行時にしか決まらない係数で割る材料は、割る前の値を焼く（係数の引数を1で束ねる）。
#
# カバレッジ判定も同じクエリへ畳み込み、1タイルあたりのDB往復を1回にする。CASE式は条件が
# falseの分岐を評価しないため、カバレッジ外ではMVT生成のサブクエリ自体が実行されない。
ROAD_SURFACE_TILE_MVT_SQL = text(
    f"""
    WITH coverage AS ({COVERAGE_SQL})
    SELECT
        coverage.covered,
        CASE WHEN coverage.covered THEN (
            SELECT ST_AsMVT(mvt.*, :layer_name, :extent, 'geom') FROM (
                SELECT
                    ST_AsMVTGeom(
                        ST_Transform(src.geom, 3857), ST_TileEnvelope(:z, :x, :y), :extent, 256, true
                    ) AS geom,
                    src.feature_key AS {ROAD_FEATURE_PROPERTIES['feature_key']},
                    -- 区間インスペクタが、ポップアップに出た値と同じ行を曖昧さ無く引き
                    -- 直すための識別子。空間マッチ（半径内最近傍）だと交差点付近で別の
                    -- 道路を拾いうる。
                    w.osm_way_id AS {ROAD_FEATURE_PROPERTIES['way_id']},
                    -- 道路名・路線番号（表示専用）。材料の正規化はかけない——利用者へ
                    -- そのまま見せる固有名詞のため。**第三者が編集できる生値で対訳表を
                    -- 持たない**ため、埋め込む側は必ずエスケープする。
                    NULLIF(btrim(w.tags->>'name'), '') AS {ROAD_FEATURE_PROPERTIES['name']},
                    NULLIF(btrim(w.tags->>'ref'), '') AS {ROAD_FEATURE_PROPERTIES['ref']},
{_MATERIAL_TILE_COLUMNS_SQL}
                FROM ({_TILE_FEATURE_SOURCE_SQL}) src
                {_TILE_MATERIAL_JOINS}
            ) mvt
            WHERE mvt.geom IS NOT NULL
        ) END AS tile
    FROM coverage
    """
).bindparams(**tile_unscaled_sql_params())


# 鍵→動的値配信層（風、「評価軸」グループ）。**タイルと同じソース**から鍵の一覧を引く。
# 別に組み立てると、単位の切り替わり方がタイルとずれた瞬間に鍵が噛み合わず、色が一切
# 付かない。ある道路の風の値は道路自身の向きに依らないため、方位は返さない。
# 中ほどは両端の平均で、ルートの区間の中点（`_EXTRA_MATERIAL_ARRAY_COLUMNS`の`mid_lat`/`mid_lon`）と同じ
# 決め方にする——区間単位のズームでは同じ区間が同じ予報の格子点へ寄る。
_FEATURE_MIDPOINTS_IN_TILE_SQL = text(
    f"""
    WITH coverage AS ({COVERAGE_SQL})
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
# 値は**そのフィーチャーに属する区間の勾配の値式を長さで重み付けた平均**
# （`domain/material_sql.py: length_weighted_mean_sql`）。区間単位のズームでは属する
# 区間が1本なのでその区間の値そのものになり、way単位のズームではwayの全区間をならした値に
# なる。1区間の外れ値がway全体を染めることは無い。基準方位が定まらない閉じた道（始点＝終点）は
# 値を返さない——どちら向きに辿るかが決まらず、0%として配ると平坦と読まれる。
_GRADIENT_SQL = material_value_sql()[GRADIENT_PERCENT]
_FEATURE_GRADIENT_INPUTS_IN_TILE_SQL = text(
    f"""
    WITH coverage AS ({COVERAGE_SQL})
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
                    round(({length_weighted_mean_sql(_GRADIENT_SQL)})::numeric, {AVERAGE_GRADE_DECIMALS})
                        ::double precision AS average_grade,
                    degrees(ref.azimuth) AS bearing_deg
                FROM ({_TILE_FEATURE_SOURCE_SQL}) src
                CROSS JOIN LATERAL (
                    -- geographyへキャストする。geometry(4326)のままだと経度緯度を平面と
                    -- して扱った角度になり、緯度35度では真の方位と数度ずれる。
                    SELECT ST_Azimuth(ST_StartPoint(src.geom)::geography,
                                      ST_EndPoint(src.geom)::geography) AS azimuth
                ) ref
                CROSS JOIN LATERAL (
                    -- 区間を道ごとに主キーの索引で引く。`OFFSET 0`は副問い合わせを外の結合へ
                    -- 畳ませないためのもの——畳まれると、道の単位と区間の単位を1つの条件で結ぶ
                    -- `OR`のために、計画が区間の表を全件読んでハッシュを作る形を選びうる。
                    SELECT * FROM road_edges r
                    WHERE r.osm_way_id = src.osm_way_id
                      AND (src.segment_index IS NULL OR r.segment_index = src.segment_index)
                    OFFSET 0
                ) re
                {material_from_clause([_GRADIENT_SQL], 're.osm_way_id', 're.segment_index')}
                WHERE ({_GRADIENT_SQL}) IS NOT NULL
                  AND ref.azimuth IS NOT NULL
                GROUP BY src.feature_key, ref.azimuth
            ) t
        ) END AS feature_gradient_inputs
    FROM coverage
    """
)


#: タイルのディスク／Redisキャッシュの鍵に入る**形の署名**。焼き込むSQLから導出するため、
#: 列や分類タグを変えれば自動的に別の鍵になる。DBの中身が作り直されたことは署名では表せず、
#: そちらは`services/tile_version_service.py`が世代の変化として扱う。
ROAD_SURFACE_TILE_SHAPE = shape_digest(ROAD_SURFACE_TILE_MVT_SQL)
#: 勾配の入力を取り出すSQLの形の署名。勾配のタイル値のキャッシュの鍵に入る
#: （`services/gradient_way_service.py: GRADIENT_VALUE_SHAPE`）。
FEATURE_GRADIENT_INPUTS_SHAPE = shape_digest(_FEATURE_GRADIENT_INPUTS_IN_TILE_SQL)


# --- way粒度の材料 -----------------------------------------------------------
#
# 材料の式は区間向けの別名を前提にする。**way1本を指すときも同じ式を使う**——wayの行から
# 同じ名前の別名を組み立てるだけで、式を2組持たない（区間インスペクタ・軸スタジオ）。
# way粒度では区間そのものの長さが無いため、`re`はwayの長さを返す1行にする。

_WAY_RE_CLAUSE = ("CROSS JOIN LATERAL (SELECT ST_Length(w.geom::geography) AS distance_m,"
                  " NULL::double precision AS bearing_deg) re")
_READS_RE = re.compile(r"(?<![\w.])re\.")


def way_from_clause(expressions: list[str], source: str | None = None) -> str:
    """式が参照する別名だけを含むFROM句。使わないJOINを足すと、材料1件のDISTINCTを引く
    だけの軸スタジオの値列挙まで重くなる。

    `source`は`w`をどう引くか（全件の走査・抽選付きの走査・主キーでの1件）。呼び出し側が
    決める——1件を引くのに走査を使うと、道の全件に対する総当たりになる。
    """
    reads_re = any(_READS_RE.search(expression) for expression in expressions)
    return (f"\nFROM {source or ways_source_sql()} w\n{_WAY_RE_CLAUSE if reads_re else ''}"
            + material_from_clause(expressions, "w.osm_way_id"))


_WAY_MATERIAL_SELECT_SQL = ", ".join(
    f"({expr}) AS m_{name}" for name, expr in sorted(material_value_sql().items())
)


_WAY_MATERIAL_VALUES_SQL = text(
    f"SELECT {_WAY_MATERIAL_SELECT_SQL}"
    + way_from_clause(list(material_value_sql().values()),
                       source=ways_lookup_sql(":osm_way_id"))
)


# 軸スタジオの分布プレビューが使うway標本。材料の式は上と同じものを使い、抽選と範囲の
# 絞り込みだけを差し替える。`TABLESAMPLE SYSTEM`はページ単位の抽選で、全表走査を避けつつ
# 広い範囲から拾える（行単位のBERNOULLIや`ORDER BY random()`は数百万行の全走査になる）。
#
# 範囲を絞るときは抽選と併用しない——`TABLESAMPLE`は表全体のページから抽選するため、
# 狭い範囲を重ねると当たるページがほとんど残らず、標本が範囲の広さに関係なく数本まで落ちる。
def _sample_way_materials_sql(sampling: str, area: str):
    return text(
        f"SELECT ST_Length(w.geom::geography) AS length_m, {_WAY_MATERIAL_SELECT_SQL}"
        + way_from_clause(list(material_value_sql().values()),
                           source=ways_source_sql(sampling))
        + f"{area} LIMIT :limit"
    )


_SAMPLE_WAY_MATERIAL_VALUES_SQL = _sample_way_materials_sql(
    "TABLESAMPLE SYSTEM (:sample_percent)", "")
_SAMPLE_WAY_MATERIAL_VALUES_IN_BBOX_SQL = _sample_way_materials_sql(
    "", " WHERE w.geom && ST_MakeEnvelope(:xmin, :ymin, :xmax, :ymax, 4326)")

_WAY_MATERIAL_COLUMN_PREFIX = "m_"

#: 地図のフィーチャー1つぶんの土地被覆。区間を指す鍵なら区間の値、指さなければ（`:segment_index`がNULL）
#: way1本の値——タイルと同じ切り替えで読む。
_FEATURE_LANDCOVER_COLUMNS = ["em.lc_valid_pixels"] + [
    f"em.lc_{landcover_key(field)}" for field in LandcoverPercentages.model_fields]
_FEATURE_LANDCOVER_SQL = text(
    f"SELECT {', '.join(_FEATURE_LANDCOVER_COLUMNS)}"
    " FROM (SELECT CAST(:osm_way_id AS bigint) AS osm_way_id,"
    " CAST(:segment_index AS smallint) AS segment_index) k"
    + material_from_clause(_FEATURE_LANDCOVER_COLUMNS, "k.osm_way_id", "k.segment_index",
                           way_when_no_segment=True)
)


def _material_values_from_row(row: Row) -> dict[str, object]:
    """way向けクエリの1行から材料id→値の辞書を作る。列別名は`m_<材料id>`で付けるため、
    材料の一覧をここへ書かない。"""
    return {
        key[len(_WAY_MATERIAL_COLUMN_PREFIX):]: value
        for key, value in row._mapping.items()
        if key.startswith(_WAY_MATERIAL_COLUMN_PREFIX)
    }


# --- 区間粒度の材料 -----------------------------------------------------------

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
    "elevation_gain_m": "em.elevation_gain_m",
    "elevation_loss_m": "em.elevation_loss_m",
}

#: 列の並びは渡した3つ組の位置で固定する。**road_edgesへLEFT JOINする**——行が無い区間で
#: 配列が短くなると、以降の列と静かにずれる。`em`は向きを解いた値で、材料の式は向きを知らずに済む。
_EDGE_MATERIAL_ARRAYS_FROM = f"""
FROM unnest(CAST(:way_ids AS bigint[]), CAST(:segment_indexes AS int[]),
            CAST(:forwards AS boolean[]))
     WITH ORDINALITY AS ids(osm_way_id, segment_index, forward, ord)
LEFT JOIN road_edges re
       ON re.osm_way_id = ids.osm_way_id AND re.segment_index = ids.segment_index
LEFT JOIN LATERAL {ways_lookup_sql('ids.osm_way_id')} w ON true
{material_from_clause([*material_value_sql().values(), *_EXTRA_MATERIAL_ARRAY_COLUMNS.values()],
                      'ids.osm_way_id', 'ids.segment_index', forward='ids.forward')}
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
)


# --- グラフの読み出し ---------------------------------------------------------
#
# 区間は向きを持たない1行で、**有向の枝は道路網全体の配列を作るとき**
# （`infrastructure/road_network_store.py`）に作る。`way_materials.direction`が逆向きの枝を
# 作ってよいかを決める。

#: 取込範囲全体の区間（向きを持たない1行）。区間は道の値の表への外部キーを持ち、通行方向は空を許さない
#: 列なので、どの区間も通行方向を持つ。並びは`domain/road_network.py`の行順の前提。
_NETWORK_EDGES_SQL = text(f"""
SELECT re.osm_way_id, re.segment_index, re.from_node_id, re.to_node_id,
       w.highway, wm.direction,
       ST_XMin(re.geom) AS min_lon, ST_YMin(re.geom) AS min_lat,
       ST_XMax(re.geom) AS max_lon, ST_YMax(re.geom) AS max_lat
FROM road_edges re
JOIN LATERAL {ways_lookup_sql("re.osm_way_id")} w ON true
{material_from_clause(["wm.direction"], "re.osm_way_id")}
ORDER BY re.osm_way_id, re.segment_index
""")

#: 区間の端点になりうるノード全件（`road_edges`の端点は`node_materials`に行を持つ）。
#: 座標はノードの生データから読み、生データが無いノードは現れない。
_NETWORK_NODES_SQL = text(f"""
SELECT nm.osm_node_id, ST_X(n.geom) AS longitude, ST_Y(n.geom) AS latitude,
       nm.has_traffic_signals, nm.max_highway_rank
FROM node_materials nm
JOIN LATERAL {nodes_lookup_sql("nm.osm_node_id")} n ON true
ORDER BY nm.osm_node_id
""")

#: 取込範囲全体の道路網（`infrastructure/road_network_store.py`）を作る読み出し。置き場の
#: 形の署名はここから導く——材料の式を変えると、作り直すべき置き場が別名になる。
NETWORK_SQL_SOURCES = (_NETWORK_EDGES_SQL, _NETWORK_NODES_SQL, _EDGE_MATERIAL_ARRAYS_SQL)

_EDGE_GEOMETRIES_SQL = text("""
SELECT re.osm_way_id, re.segment_index, re.from_node_id, re.to_node_id,
       re.distance_m, ST_AsBinary(re.geom) AS wkb
FROM unnest(CAST(:way_ids AS bigint[]), CAST(:segment_indexes AS int[]))
     AS ids(osm_way_id, segment_index)
JOIN road_edges re
  ON re.osm_way_id = ids.osm_way_id AND re.segment_index = ids.segment_index
""")


def _rows_to_directed_edges(rows, wanted: dict[tuple[int, int], list[bool]]) -> dict[str, LeanEdge]:
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
                segment_index=row.segment_index, forward=forward,
            )
    return edges


def _float_array(values: list) -> np.ndarray:
    return np.array([np.nan if v is None else float(v) for v in values], dtype=np.float64)


def _chunked(items: list, size: int):
    for start in range(0, len(items), size):
        yield items[start:start + size]


class RoadGraphRepository:
    """道路網と材料の読み出し。1つのAsyncSessionを使う。"""

    def __init__(self, session: AsyncSession):
        self._session = session

    # --- 世代・カバレッジ ----------------------------------------------------

    async def get_data_revisions(self) -> derived_data_meta.DataRevisions:
        """派生データと生データの世代。派生の世代は道路網全体の配列の置き場の名前に、
        両方が配信する地図タイルの世代に入る。"""
        return await derived_data_meta.get_revisions(self._session)

    async def get_accident_years(self) -> list[int]:
        """事故データの収録年。

        今の派生の表を作った事故の取込（`derived_data_meta.py: DerivedSourceRunRow`）の宣言（`rows.years`）を
        そのまま返す。最新の取込の宣言を読むと、取り込み直してから派生の作り直しが入れ替わるまでの間、
        古い数を新しい年数で割る。実データの発生年を数えると、事故が1件も無かった年が落ちる。
        年数は`accident_count_per_km_year`の分母に、年そのものは地図の説明文に使う。どちらもここが
        正本で、**表示側は年を自分で持たない**。
        """
        row = await self._session.execute(text(
            "SELECT r.profile->'source'->'rows'->'years' AS years"
            f" FROM {derived_data_meta.DerivedSourceRunRow.__tablename__} d"
            " JOIN source_runs r ON r.run_id = d.run_id WHERE d.source = :source"), {"source": Source.ACCIDENT})
        value = row.scalar()
        if not isinstance(value, list):
            return []
        return sorted(int(year) for year in value)

    async def get_accident_years_covered(self) -> int:
        """事故データの収録年数。`accident_count_per_km_year`の分母。"""
        return len(await self.get_accident_years())

    async def is_covered(self, bbox: BoundingBox) -> bool:
        """その範囲の生データを取り込んでいるか。判定は取込の宣言から導く。"""
        row = await self._session.execute(text(f"SELECT covered FROM ({COVERAGE_SQL}) c"), {
            "xmin": bbox.min_longitude, "ymin": bbox.min_latitude,
            "xmax": bbox.max_longitude, "ymax": bbox.max_latitude,
        })
        return bool(row.scalar())

    async def get_ingested_area(self) -> BoundingBox | None:
        """取り込んだ範囲（`is_covered`が判定に使うのと同じ範囲）。道路をまだ取り込んでいなければNone。"""
        row = (await self._session.execute(text(INGESTED_BBOX_SQL))).mappings().one_or_none()
        if row is None:
            return None
        return BoundingBox(
            min_latitude=row["min_lat"], min_longitude=row["min_lon"],
            max_latitude=row["max_lat"], max_longitude=row["max_lon"],
        )

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
        # 両向きの枝を頼まれても区間ごとに1行だけ引く（形は向きに依らず、逆向きは逆順にすれば足りる）。
        # 向きの数だけ引くと、行も問い合わせの束（`ID_CHUNK_SIZE`）の数も増える。
        wanted: dict[tuple[int, int], list[bool]] = {}
        for edge in edges:
            wanted.setdefault((edge.osm_way_id, edge.segment_index), []).append(edge.forward)
        keys = sorted(wanted)
        result: dict[str, LeanEdge] = {}
        for chunk in _chunked(keys, ID_CHUNK_SIZE):
            rows = (await self._session.execute(_EDGE_GEOMETRIES_SQL, {
                "way_ids": [k[0] for k in chunk],
                "segment_indexes": [k[1] for k in chunk],
            })).all()
            result.update(await asyncio.to_thread(_rows_to_directed_edges, rows, wanted))
        return result

    # --- 材料 ----------------------------------------------------------------

    async def get_edge_material_arrays(
        self, way_ids: list[int], segment_indexes: list[int], forwards: list[bool], accident_years_covered: int
    ) -> EdgeMaterialArrays:
        """有向の区間（`(osm_way_id, segment_index, forward)`を位置で揃えた3本の列）の材料を、
        **DB側で導出し、数値の行列と分類の列として**受け取る。

        区間数に比例するPythonの仕事を持たない。**すべての列が同じ並びを持つ**必要がある
        （1つでも違うと値が列の間で静かにずれ、エラーは出ない）。並びは渡した区間の位置
        （`WITH ORDINALITY`）で固定する。
        """
        numeric_ids, categorical_ids = material_array_columns()
        raw: dict[str, list] = {name: [] for name in MATERIAL_ARRAY_COLUMN_ORDER}
        n = len(way_ids)
        for start in range(0, n, ID_CHUNK_SIZE):
            stop = start + ID_CHUNK_SIZE
            row = (await self._session.execute(_EDGE_MATERIAL_ARRAYS_SQL, {
                "way_ids": way_ids[start:stop], "segment_indexes": segment_indexes[start:stop],
                "forwards": forwards[start:stop], "accident_years": accident_years_covered,
            })).one()
            for name in raw:
                raw[name].extend(getattr(row, f"c_{name}") or [])

        hard_filter_ids = hard_filter_columns()
        hard_filter_flags = np.empty((n, len(hard_filter_ids)), dtype=bool)
        for i, name in enumerate(hard_filter_ids):
            hard_filter_flags[:, i] = [bool(v) for v in raw[f"{_HARD_FILTER_COLUMN_PREFIX}{name}"]]

        numeric_values = np.empty((n, len(numeric_ids)), dtype=np.float64)
        for i, material_id in enumerate(numeric_ids):
            numeric_values[:, i] = _float_array(raw[material_id])

        return EdgeMaterialArrays(
            numeric_ids=numeric_ids, numeric_values=numeric_values,
            categorical_ids=categorical_ids,
            categorical_columns=tuple(CategoricalColumn.encode(raw[material_id]) for material_id in categorical_ids),
            hard_filter_ids=hard_filter_ids, hard_filter_flags=hard_filter_flags,
            distance_m=_float_array(raw["distance_m"]),
            bearing_deg=_float_array(raw["bearing_deg"]),
            mid_lat=_float_array(raw["mid_lat"]),
            mid_lon=_float_array(raw["mid_lon"]),
            elevation_present=np.array([bool(v) for v in raw["elevation_present"]], dtype=bool),
            elevation_gain_m=_float_array(raw["elevation_gain_m"]),
            elevation_loss_m=_float_array(raw["elevation_loss_m"]),
        )

    async def get_way_material_values(
        self, osm_way_id: int, accident_years_covered: int
    ) -> dict[str, object] | None:
        """way1本ぶんの材料値（材料id→スカラー）。行が無ければNone。

        区間インスペクタが使う。式は区間の評価と同じもので、way粒度の別名を
        `way_from_clause`が用意する。
        """
        rows = await self._session.execute(_WAY_MATERIAL_VALUES_SQL, {
            # 鍵はtextで渡す（`ways_lookup_sql`が主キーで引くため）。
            "osm_way_id": str(osm_way_id), "accident_years": accident_years_covered})
        row = rows.first()
        return None if row is None else _material_values_from_row(row)

    async def sample_way_material_values(
        self,
        accident_years_covered: int,
        sample_percent: float,
        limit: int,
        bbox: BoundingBox | None,
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
                for row in rows if row.length_m > 0]

    async def get_way_tags_by_osm_way_id(
        self, osm_way_id: int
    ) -> tuple[str, dict[str, str]] | None:
        """osm_way_id完全一致で(highway, tags)を返す。道は種別を必ず持つ（`source_features_way_has_kind`）。

        空間マッチ（半径内最近傍）は、交差点付近など複数の道路が近接する場所で、実際に
        クリックされたフィーチャーとは別の道路を拾いうる。フィーチャーが指す行そのものを
        引き直すことで、この不整合を構造的に防ぐ。
        """
        row = (await self._session.execute(text(f"""
            SELECT w.highway, w.tags
            FROM {ways_lookup_sql(":osm_way_id")} w
        """), {"osm_way_id": str(osm_way_id)})).first()
        if row is None:
            return None
        return (row.highway, row.tags)

    async def get_feature_landcover(
        self, osm_way_id: int, feature_key: str | None
    ) -> LandcoverPercentages | None:
        """地図でクリックされたフィーチャー1つぶんの土地被覆（区間インスペクタの内訳）。

        **地図が塗っている値と同じ単位で読む。** 鍵から区間が特定できるときは区間の値を、
        できないときはway1本の値を使う——切り替えの規則はタイルと同じもので、揃えないと
        同じ場所で地図の色と内訳の数字が食い違う。
        """
        segment = parse_edge_feature_key(feature_key) if feature_key else None
        row = (await self._session.execute(_FEATURE_LANDCOVER_SQL, {
            "osm_way_id": osm_way_id,
            "segment_index": segment[1] if segment is not None and segment[0] == osm_way_id else None,
        })).one()
        # 割合は有効画素のある行だけが全部持つ（表の制約`landcover_shares_follow_valid_pixels`）。
        if row.lc_valid_pixels is None:
            return None
        return LandcoverPercentages(**{field: getattr(row, f"lc_{landcover_key(field)}")
                                       for field in LandcoverPercentages.model_fields})

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
            text(
                f"SELECT DISTINCT {column_expr} AS value"  # noqa: S608 カタログの宣言のみ
                + way_from_clause([column_expr])
                + f" WHERE {column_expr} IS NOT NULL ORDER BY value"
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
        """路面レイヤーのMVTタイル1枚。契約は`get_tile_mvt`と同じ。"""
        return await self.get_tile_mvt(ROAD_SURFACE_TILE_MVT_SQL, ROAD_SURFACE_LAYER_NAME, z, x, y, bbox)

    async def get_tile_mvt(
        self, sql: TextClause, layer_name: str, z: int, x: int, y: int, bbox: BoundingBox
    ) -> bytes | None:
        """`(covered, tile)`の1行を返すMVT生成SQLを流し、タイル1枚をPostGIS側（ST_AsMVT）で丸ごと生成して返す。

        取込範囲外はNone（呼び出し側が空タイルへのフォールバックを判断する）。範囲内で
        対象が1つも無い場合は空バイト列（有効な空MVT、「無いことを確認済み」の
        正常応答でNoneとは区別される）。
        """
        result = await self._session.execute(sql, {
            **self._tile_params(z, x, y, bbox),
            "layer_name": layer_name, "extent": TILE_EXTENT,
        })
        covered, tile = result.one()
        if not covered:
            return None
        # 範囲内で対象0行のときST_AsMVT（集約関数）はNULLを返す。長さ0のバイト列は
        # 「featureが1つも無い有効なMVT」としてMapLibreがそのまま受理する。
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
        勾配の無い区間は平均から除き、向き（両端を結ぶ方位）が定まらないフィーチャーは返さない。"""
        result = await self._session.execute(
            _FEATURE_GRADIENT_INPUTS_IN_TILE_SQL, self._tile_params(z, x, y, bbox))
        covered, inputs = result.one()
        if not covered:
            return None
        return {str(key): (float(value[0]), float(value[1]))
                for key, value in (inputs or {}).items()}
