"""地図のタイル（路面のMVT）と、タイルと同じフィーチャーごとに値を配る読み出しのSQL。

どの読み出しも、フィーチャーの並びを`_TILE_FEATURE_SOURCE_SQL`から引き、鍵は路面のタイルが焼く`feature_key`と同じものになる。
流すのは`road_graph_repository.py: RoadGraphRepository`。
"""

from sqlalchemy import text

from app.domain.attributes import AVERAGE_GRADE_DECIMALS
from app.domain.graph import edge_feature_key_sql
from app.domain.material_catalog import (
    GRADIENT_PERCENT,
    material_tile_columns,
    material_value_sql,
    tile_unscaled_sql_params,
)
from app.domain.material_sql import length_weighted_mean_sql
from app.domain.region import EDGE_UNIT_MIN_ZOOM
from app.infrastructure.cache_identity import shape_digest
from app.infrastructure.material_joins import material_from_clause
from app.infrastructure.source_models import COVERAGE_SQL, WAYS_SOURCE_SQL, ways_lookup_sql
from app.infrastructure.vector_tile import ROAD_FEATURE_PROPERTIES

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
FEATURE_MIDPOINTS_IN_TILE_SQL = text(
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
FEATURE_GRADIENT_INPUTS_IN_TILE_SQL = text(
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
FEATURE_GRADIENT_INPUTS_SHAPE = shape_digest(FEATURE_GRADIENT_INPUTS_IN_TILE_SQL)
