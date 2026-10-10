"""配信するタイルの世代を、DBの派生データと生データの世代から実行時に組み立てる。

タイルの中身は**焼き込むSQL**（形）と**SQLが読むテーブルの中身**（世代）の2つで決まる。
形は`cache_identity.shape_digest`が自動で署名するが、中身が作り直されたことを知っているのは
バッチが進める世代（`derived_data_meta.py: get_revisions`）だけである。この2つを繋ぐのがここ。

**生データの世代は、どのソースを取り直しても全系統の鍵を変える。** 系統ごとに「読むソース」を
宣言して絞ると、その宣言は焼き込むSQLと別に持つ写しになり、SQLが新しいソースを読み始めても
誰も気づかない。取込は稀で、読まないソースの取込で変わった系統はディスクのキャッシュを
焼き直すだけで済む。

**手で書く定数を持たない。** 手で書くと、上げ忘れ（古い値を配り続ける）と、バッチ完了後に
もう一度上げ直す必要（デプロイとバッチの間に配信されたタイルが、新しい鍵のまま古い値で
キャッシュへ載る）の両方が起きる。

世代はフロントへ`GET /api/axis-catalog`の応答で配る（較正値と同じ経路。起動時に1回取るものへ
相乗りさせ、取得を増やさない）。フロントはタイルURLのクエリへ入れてブラウザのキャッシュを
分ける。

世代そのものの読み直しは`derived_data_revision_service`が持つ。ここはTTLを持たず、読む前に
読み直しを促すだけ。

**世代を使う経路（カタログ・タイルの配信）はどれも、読む前に自分で促す。** 促す場所を1つに寄せると、
そこが呼ばれるまで世代が読まれない——起動後にまだ誰もカタログを取っていなければ`x-`（まだ誰も
読んでいない印）の鍵で配り、タイルはディスクへ残らない。バッチが世代を進めた後も、そこが呼ばれるまで
古い世代の鍵のまま配り続ける。
"""

import asyncio

from app.domain.registry import TileKind
from app.infrastructure.cache_identity import DataRevisions, tile_version
from app.infrastructure.point_tile_layers import POINT_TILE_LAYERS
from app.infrastructure.region_tile_cache import prune_other_generations
from app.infrastructure.road_tile_sql import ROAD_SURFACE_TILE_SHAPE
from app.services import derived_data_revision_service


async def _fresh_revisions(repository) -> DataRevisions | None:
    """TTLが切れていれば読み直してから、いまの世代を返す。"""
    await derived_data_revision_service.refresh_current_revisions(repository)
    return derived_data_revision_service.current_revisions()


async def served_tile_version(repository, shape: str) -> str:
    """いま配信している世代（`cache_identity.tile_version`）。TTLが切れていれば世代を読み直してから組む。

    **ブラウザのURLへ入る値と、サーバー側のディスクキャッシュの鍵は同じ文字列にする。**
    形の署名だけを鍵にすると、SQLが同じままバッチが中身を作り直したとき（世代だけが動く）
    に鍵が変わらず、古い中身を配り続ける。

    `repository`はDBの世代を読める口（`get_data_revisions`）。
    """
    return tile_version(await _fresh_revisions(repository), shape)


#: 配信するタイルの系統と、その形の署名。フロントが受け取る辞書のキーでもある。点のレイヤーは
#: それぞれ自分のSQLだけから署名を持つので、1つのSQLを変えても他のレイヤーの世代は変わらない。
TILE_SHAPES: dict[TileKind, str] = {
    "road_surface": ROAD_SURFACE_TILE_SHAPE,
    **{layer.name: layer.shape for layer in POINT_TILE_LAYERS.values()},
}


async def current_tile_versions(repository) -> dict[TileKind, str]:
    """系統名→配信する世代（`cache_identity.tile_version`）。

    `repository`はDBの世代を読める口（`get_data_revisions`）。TTLの内側なら
    読み直さないため、リクエストごとに呼んでよい。
    """
    revisions = await _fresh_revisions(repository)
    return {name: tile_version(revisions, shape) for name, shape in TILE_SHAPES.items()}


async def prune_other_tile_generations(repository) -> int:
    """いま配っていない世代の地域タイルをディスクから消し、消した数を返す。

    世代はデプロイだけでなく、再起動を伴わない派生の作り直し・取込でも変わるため、定期に呼ぶ
    （`main.py`）。消す範囲の決め方は`region_tile_cache.py: prune_other_generations`。
    """
    versions = await current_tile_versions(repository)
    return await asyncio.to_thread(prune_other_generations, versions)
