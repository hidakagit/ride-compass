"""JMA動的タイル（ラスタPNG・洪水ベクタPBF）本体のRedis cache-aside。

`redis_client.py`は`decode_responses=True`（文字列前提）で生バイト列をそのまま保存
できないので、base64エンコードした文字列をJSONへ包んで1キーに保存する。
"""

import base64

from app.infrastructure.jma_tile_content import is_empty_tile
from app.infrastructure.redis_json_cache import get_json, set_json
from app.infrastructure.tile_cache import cache_key

_KEY_PREFIX = "jma:tile"
_CATEGORY = "cache:jma-tile-redis"
# プリウォーム間隔（jma_tile_prewarm_service.py、10分）より余裕を持たせ、1回のプリウォーム
# 失敗・遅延で即座に空にならないようにする。
_TTL_SECONDS = 20 * 60


class EmptyTile:
    """このパスには描くものが無いと確認済み、というキャッシュ済みの事実を表すセンチネル。

    上流の返し方には2通りある——404（タイル自体が存在しない）と、200で返るが全画素が
    透明・0バイト。降水・浸水想定区域等の疎な格子状タイルではどちらも珍しくない正常系で、
    **利用者から見れば同じ「得るものが無い」**である（クライアント側の
    `jmaTileProtocol.ts`も両方を透明タイルへ倒している）。そのため区別せずこの1つの事実
    として持つ。

    basetime/validtimeが確定した過去の一時点に対する結果のため、再フェッチしても変わらない。
    実際のタイル内容と同じキー・TTLで保持し、次回以降は上流へ問い合わせず即座に返せる
    ようにする。"""


EMPTY_TILE = EmptyTile()


def _extension(path: str) -> str:
    """`.../{z}/{x}/{y}.png`のような配信パスから拡張子だけを取り出す
    （クエリ文字列付きのパスもそのままキーになるため、末尾から素直に切る）。"""
    return path.rsplit(".", 1)[-1].split("?", 1)[0] if "." in path else ""


def _key(path: str) -> str:
    return f"{_KEY_PREFIX}:{cache_key(path)}"


async def get(path: str) -> tuple[bytes, str] | EmptyTile | None:
    """Redisキャッシュ済みなら(内容, Content-Type)または`EMPTY_TILE`を返す。
    未キャッシュ・Redis障害時はNone（呼び出し元は通常のオンデマンドフェッチへ
    フォールバックする）。"""
    payload = await get_json(_key(path), category=_CATEGORY, path=path)
    if payload is None:
        return None
    try:
        if payload.get("empty"):
            return EMPTY_TILE
        return base64.b64decode(payload["body_b64"]), payload["content_type"]
    except (AttributeError, KeyError, TypeError, ValueError):
        # JSONとしては読めるが形の違うエントリは未キャッシュ扱いにする。
        return None


async def set(path: str, content: bytes, content_type: str) -> None:
    """取得できたタイルをRedisへ書き戻す。

    中身が空なら実体ではなく`EMPTY_TILE`と同じフラグで持つ。実体を保持しても
    返す先が無い——クライアントは在否インデックス（`jma_tile_index.py`）を見て
    空のタイルを要求しないため、保持した実体が使われるのは索引が届く前だけである。
    """
    if is_empty_tile(content, _extension(path)):
        await set_empty(path)
        return
    payload = {"content_type": content_type, "body_b64": base64.b64encode(content).decode("ascii")}
    await set_json(_key(path), payload, ttl_seconds=_TTL_SECONDS, category=_CATEGORY, path=path)


async def set_empty(path: str) -> None:
    """このパスに描くものが無いと確認したときに呼ぶ（上流の404、または200で返った空タイル）。"""
    await set_json(_key(path), {"empty": True}, ttl_seconds=_TTL_SECONDS, category=_CATEGORY, path=path)
