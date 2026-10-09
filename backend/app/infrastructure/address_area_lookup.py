"""位置の辺り（その位置を含む小地域の境界に結んだ住所の区画）を、住所の区画の表と境界の生データから引く。

区画（`address_areas`）と境界の結び付き（`address_boundary_links`）は派生の段（`batch/derive_addresses.py`）が作り、
境界の多角形は生データ（`estat_small_area`）に置いたまま読む。ここは SQL の部品だけを持ち、接続を持たない——派生の段も、
要求ごとに位置の辺りを引く口も、同じ部品を自分の接続の問い合わせへ置く。辺りの名前は、引いた祖先の並びから
`domain/address_area.py: area_label`が組み立てる。
"""

from app.infrastructure.source_models import ESTAT_SMALL_AREAS_SOURCE_SQL


def boundary_area_sql(point_sql: str) -> str:
    """位置（`point_sql`。4326 の点の式）を含む小地域の境界に結んだ区画の`area_id`を出す副問い合わせ。

    辺の上の点は2つの境界に含まれるので、区画に結んだ境界のうち鍵の小さいほうにする。区画に結んだ境界に含まれなければ
    NULL（海の上・範囲の外・名前でも代表点でも結べなかった境界の中）。
    """
    return (f"(SELECT l.area_id FROM {ESTAT_SMALL_AREAS_SOURCE_SQL} e"
            " JOIN address_boundary_links l ON l.key_code = e.key_code"
            f" WHERE ST_Covers(e.geom, {point_sql}) ORDER BY e.key_code LIMIT 1)")


def area_chains_sql(area_ids_sql: str) -> str:
    """区画（`area_ids_sql`。列`area_id`を1つ出す問い合わせ）ごとに、祖先を都道府県から自分まで並べた段（`levels`）と
    名前（`names`）の配列を1行ずつ出す問い合わせ。"""
    return f"""
WITH RECURSIVE chain AS (
    SELECT a.area_id AS leaf, a.parent_id, a.level, a.name, 0 AS depth
    FROM address_areas a WHERE a.area_id IN ({area_ids_sql})
    UNION ALL
    SELECT c.leaf, a.parent_id, a.level, a.name, c.depth + 1
    FROM chain c JOIN address_areas a ON a.area_id = c.parent_id
)
SELECT leaf AS area_id, array_agg(level ORDER BY depth DESC) AS levels, array_agg(name ORDER BY depth DESC) AS names
FROM chain GROUP BY leaf
"""
