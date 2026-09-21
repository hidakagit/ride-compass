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

時刻バケットは1時間丸め（`YYYY-MM-DDTHH`、時刻に依存しない材料はNone）、向きバケットは
`BEARING_BUCKET_DEG`（5度）刻み（向きに依存しない材料はNone）、速度バケットは1km/h刻み
（速度に依存しない材料はNone）。バケット化する理由は、スライダーの連続値をそのまま
キーへ使うとキャッシュヒット率がほぼ0になるため。

TTLは呼び出し元（各材料のサービス）が渡す——風は気象データの新鮮さ
（`msm_client.update_interval_seconds`）に合わせる必要があるが、勾配は道路の向き・
標高由来の値でほぼ不変のため、材料ごとに異なる基準で決めてよい（このモジュール自体は
特定のTTL値を持たない）。

**置き場所がディスクである理由**: 失っても外部へ取りに行かず自前で再計算できるため
Redisは使わない（docs/conventions/caching.md「Redisへ置くもの・置かないもの」）。一方で1エントリが
9,500way規模で約190KBあり、キーが(タイル×向き×速度×時刻)の組み合わせで増えるため、
プロセス内メモリにも置かない。実体をRAMの外へ置き、容量上限と退避をライブラリへ委ねる
`tile_persistent_cache`（diskcache）が適する。

**正本を持たないキャッシュ**: 失っても呼び出し元が再計算すればよいだけで、失敗時は
fail-open（未キャッシュとして扱い実計算へ進む）。
"""

import asyncio
import math

from app.infrastructure import tile_persistent_cache
from app.infrastructure.road_graph_repository import ROAD_SURFACE_TILE_SHAPE

_KEY_PREFIX = "dynway"

# 向きバケットの粒度（度）。モジュールdocstring参照。
BEARING_BUCKET_DEG = 5


def bearing_bucket(bearing_deg: float) -> int:
    """向き（0〜360度、範囲外は正規化）をBEARING_BUCKET_DEG刻みのバケット番号（int）へ
    丸める。360度は0度と同じバケットに正規化する（`% 360`をBEARING_BUCKET_DEG丸めの後に
    適用するため、359度台の値がBEARING_BUCKET_DEG刻み数で割り切れずズレたバケットへ
    分類されることはない）。組み込み`round()`は偶数への銀行丸め（非対称、境界の
    バケット幅が理論値からずれる）のため、`math.floor(x+0.5)`（四捨五入、0.5は常に
    切り上げ）を使い境界幅を均一にする。"""
    normalized = bearing_deg % 360
    return math.floor(normalized / BEARING_BUCKET_DEG + 0.5) % (360 // BEARING_BUCKET_DEG)


def speed_bucket(speed_kmh: float) -> int:
    """想定速度（km/h）を1km/h刻みのバケット番号へ丸める（向きと同じ理由で連続値をそのまま
    キーにしない）。"""
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
    """指定タイル・材料・時刻バケット・向きバケット・速度バケット（速度に依存しない材料は
    None）に対応する`{鍵: 値}`を返す。
    未キャッシュ・読み出し失敗・壊れたエントリはいずれもNoneへfail-openする（呼び出し元は
    実計算へ進む）。"""
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
    """新規に計算できた`{鍵: 値}`をディスクへ書き戻す（キャッシュの最適化であり、
    書き込み失敗はレスポンス自体の成否には関与しない。失敗時は抑制付きWARNINGで記録する
    だけに留める）。"""
    key = _key(material_id, z, x, y, hour_bucket, bearing_deg, speed_kmh, revision)
    await asyncio.to_thread(
        tile_persistent_cache.set_by_key, key, dict(values), tag=f"{_KEY_PREFIX}:{material_id}", expire=ttl_seconds
    )
