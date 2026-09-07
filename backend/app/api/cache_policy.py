"""HTTPキャッシュポリシー（`Cache-Control`）の一元管理。

各エンドポイントが応答へ個別に`Cache-Control`を書くと、方針がルーター全体へ散らばり
「どのAPIがどれだけキャッシュされるか」を一覧できなくなる。パスとポリシーの対応表
（`_ROUTE_POLICIES`）をこの1箇所へ集め、`CachePolicyMiddleware`が応答へ付与する。
新しいエンドポイントを追加したときは、この表へも1行足す（足し忘れは
`tests/test_cache_policy.py`が全ルートを走査して機械的に検出する）。

**2xxにしか付けない**: 上流障害（502）等の一時的な失敗をキャッシュさせると障害が
実際の復旧より長く尾を引く。エラー応答をあえてキャッシュさせたい場合（`jma_tile.py`の
恒久404）はハンドラ側で明示する。

**ハンドラ側の明示が優先**: ハンドラが自分で`Cache-Control`を設定した応答には触らない。
同じパスでも内容の性質でポリシーが分かれるエンドポイント（`/api/jma-tile/`のタイル本体・
時刻一覧・恒久404）は`HANDLER_MANAGED`を表へ置き、実際の値をハンドラが決める。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send


@dataclass(frozen=True)
class CachePolicy:
    """1つのキャッシュ方針。`header()`が実際の`Cache-Control`値を組み立てる。

    `max_age_seconds=None`は`no-store`（保存自体を禁じる）を意味する。`immutable`は
    「URLが同じなら内容も同じ」と保証できる場合のみ真にしてよい——ブラウザはリロード時の
    条件付きリクエストすら省くため、内容が更新されうるURLに付けると更新が届かなくなる。
    """

    max_age_seconds: int | None
    immutable: bool = False
    handler_managed: bool = False

    def header(self) -> str:
        if self.max_age_seconds is None:
            return "no-store"
        value = f"public, max-age={self.max_age_seconds}"
        return f"{value}, immutable" if self.immutable else value


# --- ポリシーの語彙 -----------------------------------------------------------
# 時間の調整はここだけで行う。同じ秒数でも意味が違うものは別の定数として持つ
# （片方だけを後から動かせるようにするため）。

#: 配信元が更新しない静的データ（国土地理院の色別標高図タイル）。
PERMANENT = CachePolicy(max_age_seconds=24 * 60 * 60, immutable=True)
#: URLに`basetime`/`validtime`を含み内容が確定して以後変化しないタイル（気象庁）。
#: `max-age`は`jma_tile_redis_cache.py`のTTLと揃える。
IMMUTABLE_TILE = CachePolicy(max_age_seconds=20 * 60, immutable=True)
#: 取込バッチが走るまで変化しないタイル（路面・事故・POI）。
BATCH_TILE = CachePolicy(max_age_seconds=60 * 60)
#: 基礎地図（OpenFreeMap）。「変わらないデータを更新」ボタン（`POST /api/basemap/refresh`）
#: はサーバー側のファイルキャッシュしか消せずブラウザの保持分へ手が届かないため、押した
#: 効果がこの`max-age`ぶん遅れて現れる。押す頻度と表示速度の釣り合いで10分にしてある。
BASEMAP = CachePolicy(max_age_seconds=10 * 60)
#: コード変更＋デプロイでしか変わらないカタログ、およびDB取込頻度が月単位の値一覧。
CATALOG = CachePolicy(max_age_seconds=60 * 60)
#: 数分の再利用で表示が古くならないもの（風グリッド・材料タイル・天候予報）。
SHORT = CachePolicy(max_age_seconds=5 * 60)
#: 数分で変わりうる警戒情報・実測値。
VOLATILE = CachePolicy(max_age_seconds=2 * 60)
#: 管理GUIでの変更が再デプロイなしに即座に反映される必要があるもの（軸カタログ）。
LIVE = CachePolicy(max_age_seconds=60)
#: 進捗ポーリング・管理情報・状態確認。無指定はキャッシュ禁止と同義ではなく、中間プロキシや
#: ブラウザのヒューリスティック判断に委ねられるため、禁止したいものは明示する。
NO_STORE = CachePolicy(max_age_seconds=None)
#: 同じパスでも内容の性質でポリシーが分かれるため、どれを使うかをハンドラ側が選ぶもの。
#: 選択肢そのもの（下のJMA_*）はここに置き、キャッシュ時間の定義がこのファイルの外へ
#: 漏れないようにする。
HANDLER_MANAGED = CachePolicy(max_age_seconds=None, handler_managed=True)

#: 気象庁の時刻一覧（`targetTimes*.json`）。同じURLのまま内容が更新されるため`immutable`に
#: できず、新しいフレームの発見が遅れないよう`JmaTileClient`のプロセス内TTLCache（2分）より
#: 短くする。
JMA_TARGET_TIMES = CachePolicy(max_age_seconds=60)
#: 気象庁タイルの恒久404。`basetime`が確定した過去の一時点に対する結果のため再問い合わせ
#: しても変わらない（`jma_tile_redis_cache.py: TileNotFound`と同じ理由）。疎な格子状タイルでは
#: 404が正常系として多数発生するため、再要求させない効果はタイル本体と変わらない。
JMA_TILE_NOT_FOUND = CachePolicy(max_age_seconds=10 * 60)


# --- パスとポリシーの対応表 ---------------------------------------------------
# 前方一致で引き、複数該当する場合は最も長いパターンを採る（表の記載順に依存しない）。
_ROUTE_POLICIES: Final[tuple[tuple[str, CachePolicy], ...]] = (
    # 地図タイル系（1画面あたり数十〜数百枚が飛ぶ。キャッシュの有無が最も効く）
    # 在否インデックスはプリウォーム（10分間隔）ごとに内容が変わる。古いものを掴むと
    # 「中身があるのに取りに行かない」ことになるため短命にする。
    ("/api/jma-tile-index", LIVE),
    ("/api/jma-tile/", HANDLER_MANAGED),
    ("/api/gsi-relief-tile/", PERMANENT),
    ("/api/basemap/refresh", NO_STORE),
    ("/api/basemap/", BASEMAP),
    ("/api/region/road-surface-tiles/", BATCH_TILE),
    ("/api/region/accident-tiles/", BATCH_TILE),
    ("/api/region/poi-tiles/", BATCH_TILE),
    ("/api/region/dynamic-way-values/", SHORT),
    # カタログ・設定
    ("/api/axis-catalog", LIVE),
    ("/api/material-catalog", CATALOG),
    # 天候（URLに緯度経度を含むため地点ごとに別エントリになる）
    ("/api/weather/wind-grid", SHORT),
    ("/api/weather/warnings", VOLATILE),
    ("/api/weather/wbgt", VOLATILE),
    ("/api/weather/flood-forecast", VOLATILE),
    ("/api/weather/amedas", VOLATILE),
    ("/api/weather", SHORT),
    # ルート生成（POSTはそもそもキャッシュされないが、進捗のGETは明示的に禁じる）
    ("/api/routes/", NO_STORE),
    ("/api/region/axis-inspector", NO_STORE),
    # 管理・状態確認（認可必須の情報を中間キャッシュへ残さない）
    ("/api/admin/", NO_STORE),
    ("/api/debug/", NO_STORE),
    ("/health", NO_STORE),
)


def policy_for_path(path: str) -> CachePolicy | None:
    """パスに対応するポリシーを返す（該当が無ければNone）。

    複数のパターンが前方一致する場合は最長のものを採るため、表への追記順を気にしなくてよい
    （例: `/api/basemap/refresh`は`/api/basemap/`より長いので必ず前者が勝つ）。
    """
    best: tuple[int, CachePolicy] | None = None
    for prefix, policy in _ROUTE_POLICIES:
        if path.startswith(prefix) and (best is None or len(prefix) > best[0]):
            best = (len(prefix), policy)
    return best[1] if best is not None else None


class CachePolicyMiddleware:
    """`_ROUTE_POLICIES`に基づき応答へ`Cache-Control`を付ける。

    ボディに触れないため、`response_compression.py`と同じくASGI生の実装にしてある
    （`http.response.start`のヘッダだけを書き換える）。
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        policy = policy_for_path(scope["path"])
        if policy is None or policy.handler_managed:
            await self.app(scope, receive, send)
            return

        async def send_with_policy(message: Message) -> None:
            if message["type"] == "http.response.start" and 200 <= message["status"] < 300:
                headers = MutableHeaders(raw=message["headers"])
                if "cache-control" not in headers:
                    headers["Cache-Control"] = policy.header()
            await send(message)

        await self.app(scope, receive, send_with_policy)
