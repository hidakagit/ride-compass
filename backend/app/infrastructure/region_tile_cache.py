"""地域タイル（路面・点・土地被覆）のディスクの口。鍵（`cache_identity.py`）・キャッシュ確認→取得→書き戻しの骨格・
旧世代の掃除を持ち、配信のサービスとは系統・世代・座標の値でやり取りする。

取得不可の理由をどうWARNINGログへ出すか（文言・`fields`への記録内容）はタイル種別ごとに
違う（「取込範囲外」「DB障害」等）ため、その判断とログ出力は呼び出し元が渡す
`fetch_tile`の責務にしてある。
"""

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

from app.domain.registry import TileKind
from app.infrastructure import landcover_raster, tile_cache
from app.infrastructure.cache_identity import (
    LANDCOVER_TILE_VERSION,
    is_known_tile_version,
    raster_set_fingerprint,
    region_tile_generation_prefix,
    region_tile_key,
    region_tile_kind,
)
from app.infrastructure.debug_log import log_external_call

#: 土地被覆ラスタタイルの系統名。DBの世代を持たないので、世代の表（`TileKind`）の外にある。
LANDCOVER_TILE_KIND = "landcover"

#: 旧世代を消す間隔。世代が変わるのは派生の作り直し・取込・タイルのSQLを変えたデプロイで、どれも日に1回より
#: 稀なので、消し遅れて積むのはおおむね1世代ぶんで済む（それ以上は容量の上限が退避する）。
PRUNE_INTERVAL_HOURS = 24


@dataclass(frozen=True)
class TileResponse:
    """タイル本体と、それをブラウザへ長期キャッシュさせてよいかどうか。

    取得不可（`fetch_tile`が`None`）のとき返す空タイルには2種類ある——「取込範囲外で
    恒久的にデータが無い」場合と、「DB障害・混雑で一時的に取れなかった」場合である。
    後者を`api/cache_policy.py: BATCH_TILE`（1時間）でキャッシュさせると、サーバーが
    回復した後も利用者のブラウザにはその区画の空白が1時間残り続ける。サーバー側の
    ファイルキャッシュには書かない（下記`serve_region_tile`参照）ため次のリクエストでは
    正しく生成され、**取り残されるのはブラウザ側だけ**という気づきにくい壊れ方をする。
    """

    content: bytes
    cacheable: bool = True


def landcover_generation() -> str:
    """土地被覆ラスタタイルのディスクの世代。**実際に開けているラスタの構成**も入れる。

    タイルの中身はどのラスタを開いていたかに従属する。対応範囲を広げるためゾーンを1枚
    足しても鍵が同じだと、継ぎ目のタイルは古い絵（片側が透明のまま）を返し続ける。
    設定された一覧ではなく開けている一覧を使うのは、**起動時に1枚だけ置かれていなかった
    場合も同じことが起きる**ため——そのとき設定の側で鍵を作ると、欠けたゾーンの透明な絵が
    「完全な構成」の鍵で恒久的に残る。
    """
    raster_set = raster_set_fingerprint(landcover_raster.opened_raster_paths())
    return f"{LANDCOVER_TILE_VERSION}/{raster_set}"


async def serve_region_tile(
    *,
    kind: str,
    generation: str,
    z: int,
    x: int,
    y: int,
    extension: str,
    empty_tile: bytes,
    content_type: str,
    external_call_name: str,
    fetch_tile: Callable[[dict], Awaitable[bytes | None]],
    source_label: str = "postgis",
) -> TileResponse:
    """キャッシュにあればそれを、無ければ`fetch_tile`で作ったものを返す。

    取得不可が一時的な失敗（`fetch_tile`が`debug_log.py: mark_failed`で失敗を記録した場合）
    だったときは`cacheable=False`で返す。呼び出し元のルーターはこれを見て
    `Cache-Control: no-store`を明示する（`TileResponse`のdocstring参照）。

    世代を読めていない（`cache_identity.py: is_known_tile_version`が偽）ときはディスクへ書かずに返す。
    **どの世代の中身か分からないまま焼いたタイルを残さない**ため——残すと後で世代が判明しても正しいものと区別できない
    （`infrastructure/cache_identity.py: UNKNOWN_REVISION`）。
    """
    key = region_tile_key(kind, generation, z, x, y, extension)
    with log_external_call(external_call_name, z=z, x=x, y=y) as fields:
        cached = await asyncio.to_thread(tile_cache.get, key)
        if cached is not None:
            fields["cache"] = "hit"
            content, _content_type = cached
            return TileResponse(content)
        fields["cache"] = "miss"

        tile_bytes = await fetch_tile(fields)
        if tile_bytes is None:
            fields["source"] = "uncovered_empty"
            return TileResponse(empty_tile, cacheable=fields.get("result") != "error")

        # どこから作ったか（`source_label`）はタイル種別で違う。/api/debug/statsの内訳が
        # 実際の取得元と食い違わないよう、呼び出し元が名乗る。
        fields["source"] = source_label
        fields["tile_bytes"] = len(tile_bytes)
        persist = fields["persisted"] = is_known_tile_version(generation)
        if persist:
            await asyncio.to_thread(tile_cache.set, key, tile_bytes, content_type)
        return TileResponse(tile_bytes)


def prune_other_generations(tile_versions: Mapping[TileKind, str]) -> int:
    """配っていない世代の地域タイルをディスクから消し、消した数を返す。

    `tile_versions`はDBの世代から組んだ系統名→配信する世代（`services/tile_version_service.py:
    current_tile_versions`）。土地被覆の世代はここで足す。

    - 世代を読めていない系統（DBの世代が読めない・土地被覆のラスタが1枚も開けない）は消さない——
      どれが今の世代か分からない。
    - どの系統の表にも無い系統（改名・廃止した系統）の鍵は消す——もう誰も読まない。
    """
    generations: dict[str, str | None] = {
        kind: version if is_known_tile_version(version) else None for kind, version in tile_versions.items()
    }
    generations[LANDCOVER_TILE_KIND] = landcover_generation() if landcover_raster.has_sources() else None

    def is_stale(key: str) -> bool:
        kind = region_tile_kind(key)
        if kind is None:
            return False
        if kind not in generations:
            return True
        generation = generations[kind]
        return generation is not None and not key.startswith(region_tile_generation_prefix(kind, generation))

    return tile_cache.delete_where(is_stale)
