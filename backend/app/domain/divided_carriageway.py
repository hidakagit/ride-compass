"""「上下線が分かれた道の片側か」の判定（しきい値と、判定のSQL式）。

OSMは中央分離帯のある道路の上下線を別々のwayとして持ち、その一本ずつに`oneway=yes`を
付ける。そのためタグだけでは「一方通行規制の道」と「上下線が分かれた道の片側」を
区別できず、一方通行として塗ると後者まで塗ってしまう（後者は道路としては双方向で、
逆方向は数m隣にある）。判定は逆向きに並走する相方の有無で行う。
"""

from app.domain.traffic import DIRECTION_BACKWARD, one_way_sql

#: 同じ路線番号/名前を持つ相方を探すときの横方向の距離（m）。名前が一致している時点で
#: 同じ道路だとOSM自身が言っているため、間隔そのものは広めに許す。
NAMED_GAP_M = 40.0

#: 名前に頼らず幾何だけで判定するときの距離（m）。上下線分離の間隔（幹線で中央値10m前後）
#: と、街区を挟んで並ぶ別々の一方通行路地の間隔（中央値20m弱）が分布として分かれる、
#: その谷間に置く値。
GEOMETRIC_GAP_M = 15.0

#: 前置フィルタの箱を度へ直すときの、1度あたりの距離（m）。**距離の判定より必ず広い箱に
#: なるよう小さめに取る**——箱の方が狭いと、距離をいくつに設定しても箱の大きさが実効の
#: 上限になり、しきい値を緩めても何も変わらない。関東の緯度では経度1度が89〜91kmのため、
#: 80,000mなら常に広い側へ倒れる。
PREFILTER_METERS_PER_DEGREE = 80_000.0

#: 「逆向き」と見なす進行方位の差の許容（度、180度からのずれ）。カーブの途中で上下線の
#: 向きがずれるぶんを吸収する。
BEARING_TOLERANCE_DEG = 45.0

#: 「全長にわたって寄り添う」を確かめる標本点の位置（線長に対する割合）。端点ちょうどは
#: 交差点で他の道と接するため、少し内側から取る。
SAMPLE_FRACTIONS = (0.05, 0.25, 0.5, 0.75, 0.95)

#: OSMが「上下線が分かれている」と言っている`carriageway`の値。
TAG_VALUES = ("dual", "triple", "2")


def facts_sql(way: str, direction: str) -> str:
    """`divided_sql`が読む道1本の値を出すSELECTの列（`carriageway`・`ident`・`travel_deg`）。

    `way`は道の行（`tags`・`geom`を持つ）、`direction`はその道の通行方向の式。
    """
    return f"""lower(btrim(coalesce({way}.tags->>'carriageway', ''))) AS carriageway,
       COALESCE(NULLIF(btrim({way}.tags->>'ref'), ''), NULLIF(btrim({way}.tags->>'name'), '')) AS ident,
       degrees(ST_Azimuth(ST_StartPoint({way}.geom)::geography, ST_EndPoint({way}.geom)::geography))
           + CASE WHEN {direction} = '{DIRECTION_BACKWARD}' THEN 180 ELSE 0 END AS travel_deg"""


def _antiparallel_sql(row: str) -> str:
    """`row`と相方`b`が逆向きに並走しているか。"""
    return f"abs(((b.travel_deg - {row}.travel_deg)::numeric % 360 + 360) % 360 - 180) < {BEARING_TOLERANCE_DEG}"


def divided_sql(row: str, candidates: str) -> str:
    """道の行`row`が上下線の分かれた道の片側かのSQL式。

    `row`と相方の候補の関係`candidates`は、どちらも`osm_way_id`・`geom`・`direction`・`highway`と
    `facts_sql`の列を持つ。
    """
    fractions = ", ".join(str(f) for f in SAMPLE_FRACTIONS)
    named_deg = NAMED_GAP_M / PREFILTER_METERS_PER_DEGREE
    geometric_deg = GEOMETRIC_GAP_M / PREFILTER_METERS_PER_DEGREE
    tag_values = ", ".join(f"'{value}'" for value in TAG_VALUES)
    antiparallel = _antiparallel_sql(row)
    return f"""{one_way_sql(f"{row}.direction")} AND {row}.travel_deg IS NOT NULL AND (
               -- 条件1: OSM自身の申告
               {row}.carriageway = ANY(ARRAY[{tag_values}])
               -- 条件2: 同じ路線番号/名前の対向一方通行が近くにある
               OR ({row}.ident IS NOT NULL AND EXISTS (
                   SELECT 1 FROM {candidates} b
                   WHERE b.osm_way_id <> {row}.osm_way_id
                     AND {one_way_sql("b.direction")}
                     AND b.ident = {row}.ident
                     AND b.geom && ST_Expand({row}.geom, {named_deg})
                     AND ST_DWithin({row}.geom::geography, b.geom::geography, {NAMED_GAP_M})
                     AND {antiparallel}
               ))
               -- 条件3: 全長にわたって対向する同種別の一方通行が寄り添う
               OR NOT EXISTS (
                   SELECT 1 FROM unnest(ARRAY[{fractions}]::double precision[]) AS f
                   WHERE NOT EXISTS (
                       SELECT 1 FROM {candidates} b
                       WHERE b.osm_way_id <> {row}.osm_way_id
                         AND {one_way_sql("b.direction")}
                         AND b.highway = {row}.highway
                         -- 名前が食い違う道どうしは対にしない（両方無名は許す）。
                         -- 主線に沿う側道を上下線の片側と見なさないため。
                         AND (b.ident IS NOT DISTINCT FROM {row}.ident
                              OR {row}.ident IS NULL OR b.ident IS NULL)
                         -- 前置フィルタは標本点まわりの小さな箱にする（wayの全体bboxで
                         -- 広げると長い道で候補が爆発する）。索引を使わせるためにあり、
                         -- 正確な距離は次の行が決める。
                         AND b.geom && ST_Expand(
                               ST_LineInterpolatePoint({row}.geom, f), {geometric_deg})
                         AND ST_DWithin(
                               ST_LineInterpolatePoint({row}.geom, f)::geography,
                               b.geom::geography, {GEOMETRIC_GAP_M})
                         AND {antiparallel}
                   )
               )
           )"""


def oneway_material_sql(direction: str, divided: str) -> str:
    """一方通行の道かのSQL式（材料`oneway`の値）。上下線が分かれた道の片側は外す。"""
    return f"{one_way_sql(direction)} AND NOT COALESCE({divided}, false)"
