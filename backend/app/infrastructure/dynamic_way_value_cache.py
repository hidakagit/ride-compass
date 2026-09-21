"""動的＋向きあり材料の「フィーチャー→値」配信専用のディスクキャッシュ。
路面タイルのフィーチャー別の動的値を配るレイヤーで、材料そのものの取得層とは別レイヤー。

キーは`(路面タイルの世代, material_id, z, x, y, 時刻バケット, 向きバケット, 速度バケット)`。
値は`{feature_key: 値}`のdict——風のように「タイル内全フィーチャーが同値」の場合も勾配の
ように「フィーチャー単位で異なる値」の場合も同じ表現で吸収するため、材料側は「タイル単位で
いくつ値を返すか」を意識せずこのモジュールを共有できる（風は
dict.fromkeys(feature_keys, penalty)で作った「全キー同値」のdictを渡すだけ）。

**キーへタイルの世代（`<DBの世代>-<形の署名>`）を含める理由**: ここに入る鍵は路面タイルの
`feature_key`と一字一句一致して初めて意味を持つ（フロントが`setFeatureState`のidとして使う）。
鍵の中身は**形の署名だけでは決まらない**——`feature_key`は`road_edges`の中身そのもので、
バッチが作り直せば同じSQLでも別の値になる。形の署名だけを鍵にすると、世代をまたいだ
エントリがどの地物にも一致しないまま生き残り、TTLが切れるまで（勾配は24時間）色が静かに
消える。バケット（向き5度・速度1km/h）ごとに新旧が混ざるため、「コンパスを少し回すと
色が出たり消えたりする」形で出る。

DBの世代は**呼び出し側が必須キーワードで渡す**（`revision`）。infrastructureから
`services/derived_data_revision_service.py`を読むと依存が逆向きになるため、ここでは受け取る
だけにする。省略できない形にしてあるので、新しい材料を足したときに渡し忘れると
その場で失敗する（静かに古い値を配るより良い）。

時刻・向き・速度はバケットへ丸めてからキーにする（材料が依存しない軸はNone）。
スライダーの連続値をそのままキーへ使うとヒット率がほぼ0になるため。

TTLは呼び出し元（各材料のサービス）が渡す。風は気象データの新鮮さに合わせる必要があるが、
勾配は道路の向き・標高由来でほぼ不変、と材料ごとに基準が違うため。
"""

import asyncio
import math

from app.infrastructure import tile_persistent_cache
from app.infrastructure.road_graph_repository import ROAD_SURFACE_TILE_SHAPE

_KEY_PREFIX = "dynway"

BEARING_BUCKET_DEG = 5


def bearing_bucket(bearing_deg: float) -> int:
    """向き（度、範囲外は正規化）をバケット番号へ丸める。360度は0度と同じバケットになる。

    組み込み`round()`は偶数への銀行丸めで境界のバケット幅が理論値からずれるため、
    `math.floor(x+0.5)`で境界幅を均一にする。
    """
    normalized = bearing_deg % 360
    return math.floor(normalized / BEARING_BUCKET_DEG + 0.5) % (360 // BEARING_BUCKET_DEG)


def speed_bucket(speed_kmh: float) -> int:
    """想定速度（km/h）を1km/h刻みのバケット番号へ丸める。"""
    return math.floor(speed_kmh + 0.5)


def _key(
    material_id: str, z: int, x: int, y: int, hour_bucket: str | None, bearing_deg: float | None,
    speed_kmh: float | None, revision: int | None,
) -> tuple:
    bearing_token = bearing_bucket(bearing_deg) if bearing_deg is not None else None
    speed_token = speed_bucket(speed_kmh) if speed_kmh is not None else None
    return (
        _KEY_PREFIX, revision, ROAD_SURFACE_TILE_SHAPE, material_id, z, x, y,
        hour_bucket, bearing_token, speed_token,
    )


async def get_tile_values(
    material_id: str, z: int, x: int, y: int, hour_bucket: str | None, bearing_deg: float | None,
    speed_kmh: float | None = None, *, revision: int | None,
) -> dict[str, float] | None:
    """該当バケットの`{フィーチャー鍵: 値}`。未キャッシュ・読み出し失敗はいずれもNone。"""
    key = _key(material_id, z, x, y, hour_bucket, bearing_deg, speed_kmh, revision)
    return await asyncio.to_thread(tile_persistent_cache.get_by_key, key)


async def set_tile_values(
    material_id: str,
    z: int,
    x: int,
    y: int,
    hour_bucket: str | None,
    bearing_deg: float | None,
    values: dict[str, float],
    ttl_seconds: int,
    speed_kmh: float | None = None,
    *,
    revision: int | None,
) -> None:
    """新規に計算できた`{フィーチャー鍵: 値}`をディスクへ書き戻す。"""
    key = _key(material_id, z, x, y, hour_bucket, bearing_deg, speed_kmh, revision)
    await asyncio.to_thread(
        tile_persistent_cache.set_by_key, key, dict(values), tag=f"{_KEY_PREFIX}:{material_id}", expire=ttl_seconds
    )
