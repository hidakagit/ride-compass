"""勾配の「フィーチャー→値」配信専用のディスクキャッシュ。
路面タイルのフィーチャー別の動的値を配るレイヤーで、材料そのものの取得層とは別レイヤー。
配信する材料のうちキャッシュするのは勾配だけで、時刻・速度に依る材料（風）はキャッシュしない
（docs/modules/backend/dynamic-way-values.md「キャッシュ」節）。

キーは`(路面タイルの世代, material_id, 材料の値の作り方の署名, z, x, y, 向きバケット)`。
値は配信サービスが返すのと同じ`{feature_key: 値}`のdict。

材料の値の作り方の署名（`value_shape`）も呼び出し側が必須キーワードで渡す。材料単位の失効を
消去でなく鍵で表す理由は docs/modules/backend/dynamic-way-values.md「キャッシュ」節。

**キーへ路面タイルの世代（`cache_identity.py: tile_version`）を含める理由**: ここに入る鍵は路面タイルの
`feature_key`と一字一句一致して初めて意味を持つ（フロントが`setFeatureState`のidとして使う）。
鍵の中身は**形の署名だけでは決まらない**——`feature_key`は`road_edges`の中身そのもので、
バッチが作り直せば同じSQLでも別の値になる。形の署名だけを鍵にすると、世代をまたいだ
エントリがどの地物にも一致しないまま生き残り、TTLが切れるまで（勾配は24時間）色が静かに
消える。向きのバケット（5度）ごとに新旧が混ざるため、「コンパスを少し回すと色が出たり
消えたりする」形で出る。

路面タイルの世代は**呼び出し側が必須キーワードで渡す**（`surface_tile_version`。配信している路面タイルと
同じ文字列）。infrastructureから`services/tile_version_service.py`を読むと依存が逆向きになるため、
ここでは受け取るだけにする。省略できない形にしてあるので、新しい材料を足したときに渡し忘れると
その場で失敗する（静かに古い値を配るより良い）。

向きはバケットへ丸めてからキーにする。スライダーの連続値をそのままキーへ使うとヒット率が
ほぼ0になるため。
"""

import asyncio
import math

from app.infrastructure import tile_persistent_cache

_KEY_PREFIX = "dynway"

BEARING_BUCKET_DEG = 5

# 勾配の入力は道路の向きと標高で決まりほぼ不変のため、鮮度の制約が無い。長く持って
# DBへの再問い合わせを抑える。正本を持たないキャッシュで、期限切れ後は再計算されるだけ。
_TTL_SECONDS = 24 * 3600


def bearing_bucket(bearing_deg: float) -> int:
    """向き（度、範囲外は正規化）をバケット番号へ丸める。360度は0度と同じバケットになる。

    組み込み`round()`は偶数への銀行丸めで境界のバケット幅が理論値からずれるため、
    `math.floor(x+0.5)`で境界幅を均一にする。
    """
    normalized = bearing_deg % 360
    return math.floor(normalized / BEARING_BUCKET_DEG + 0.5) % (360 // BEARING_BUCKET_DEG)


def _key(
    material_id: str, z: int, x: int, y: int, bearing_deg: float, surface_tile_version: str, value_shape: str
) -> tuple:
    return (
        _KEY_PREFIX, surface_tile_version, material_id, value_shape, z, x, y, bearing_bucket(bearing_deg),
    )


async def get_tile_values(
    material_id: str, z: int, x: int, y: int, bearing_deg: float, *, surface_tile_version: str, value_shape: str,
) -> dict[str, float | None] | None:
    """該当バケットの`{フィーチャー鍵: 値}`。未キャッシュ・読み出し失敗はいずれもNone。

    値の無いタイルは空のdictとして返り、Noneとは別に扱われる（呼び出し元はNoneのときだけ計算し直す）。
    """
    key = _key(material_id, z, x, y, bearing_deg, surface_tile_version, value_shape)
    return await asyncio.to_thread(tile_persistent_cache.get_by_key, key)


async def set_tile_values(
    material_id: str,
    z: int,
    x: int,
    y: int,
    bearing_deg: float,
    values: dict[str, float | None],
    *,
    surface_tile_version: str,
    value_shape: str,
) -> None:
    """新規に計算できた`{フィーチャー鍵: 値}`をディスクへ書き戻す。"""
    key = _key(material_id, z, x, y, bearing_deg, surface_tile_version, value_shape)
    await asyncio.to_thread(tile_persistent_cache.set_by_key, key, dict(values), expire=_TTL_SECONDS)
