"""JMA動的タイル（ラスタPNG・洪水ベクタPBF）本体のRedis cache-aside。

値はContent-Type・NULバイト・本体をこの順につないだ生のバイト列で1キーに持ち、ヒットのたびにデコードを払わない。
0バイトの値は「描くものが無い」（`EMPTY_TILE`）を表す——中身が空のタイルは実体を保存しないため、
本物のタイルと重ならない。
"""

import hashlib

from app.infrastructure.jma_tile_content import is_empty_tile
from app.infrastructure.jma_tile_recolor import RECOLOR_VERSION
from app.infrastructure.redis_json_cache import get_bytes, set_bytes

# 保存するのは中継が塗り替えたあとのタイルなので、塗り替えの版を鍵に入れる。
_KEY_PREFIX = f"jma:tile:{RECOLOR_VERSION}"
_CATEGORY = "cache:jma-tile-redis"
# プリウォーム間隔（jma_tile_prewarm_service.py、10分）より余裕を持たせ、1回のプリウォーム
# 失敗・遅延で即座に空にならないようにする。
_TTL_SECONDS = 20 * 60


class EmptyTile:
    """このパスには描くものが無いと確認済み、というキャッシュ済みの事実を表すセンチネル。

    上流の返し方には2通りある——404（タイル自体が存在しない）と、200で返るが全画素が
    透明・0バイト。降水・浸水想定区域等の疎な格子状タイルではどちらも珍しくない正常系で、
    **利用者から見れば同じ「得るものが無い」**である。そのため区別せずこの1つの事実
    として持つ。

    配信された一時点に対する結果のため、再フェッチしても変わらない。実際のタイル内容と同じキー・TTLで
    保持し、次回以降は上流へ問い合わせず即座に返せるようにする。配信前にも返る404（コマごとの地物）は
    確定しないので、この事実として持たない（`domain/jma_tile_specs.py: is_final_absence`）。"""


EMPTY_TILE = EmptyTile()


def _extension(path: str) -> str:
    """`.../{z}/{x}/{y}.png`のような配信パスから拡張子だけを取り出す
    （クエリ文字列付きのパスもそのままキーになるため、末尾から素直に切る）。"""
    return path.rsplit(".", 1)[-1].split("?", 1)[0] if "." in path else ""


def _key(path: str) -> str:
    return f"{_KEY_PREFIX}:{hashlib.sha256(path.encode('utf-8')).hexdigest()}"


def _decode(raw: bytes) -> tuple[bytes, str] | EmptyTile:
    if raw == b"":
        return EMPTY_TILE
    content_type, _separator, content = raw.partition(b"\0")
    return content, content_type.decode("latin-1")


async def get(path: str) -> tuple[bytes, str] | EmptyTile | None:
    """Redisキャッシュ済みなら(内容, Content-Type)または`EMPTY_TILE`を返す。
    未キャッシュ・Redis障害時はNone（呼び出し元は通常のオンデマンドフェッチへ
    フォールバックする）。"""
    return await get_bytes(_key(path), decode=_decode, category=_CATEGORY, path=path)


async def set(path: str, content: bytes, content_type: str) -> None:
    """取得できたタイルをRedisへ書き戻す。

    中身が空なら実体ではなく`EMPTY_TILE`と同じフラグで持つ。実体を保持しても
    返す先が無い——クライアントは在否インデックス（`jma_tile_index.py`）を見て
    空のタイルを要求しないため、保持した実体が使われるのは索引が届く前だけである。
    """
    if is_empty_tile(content, _extension(path)):
        await set_empty(path)
        return
    value = content_type.encode("latin-1", errors="replace") + b"\0" + content
    await set_bytes(_key(path), value, ttl_seconds=_TTL_SECONDS, category=_CATEGORY, path=path)


async def set_empty(path: str) -> None:
    """このパスに描くものが無いと確認したときに呼ぶ（上流の確定した404、または200で返った空タイル）。"""
    await set_bytes(_key(path), b"", ttl_seconds=_TTL_SECONDS, category=_CATEGORY, path=path)
