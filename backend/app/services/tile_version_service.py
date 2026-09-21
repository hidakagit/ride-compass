"""配信するタイルの世代を、DBの派生データ世代から実行時に組み立てる。

タイルの中身は**焼き込むSQL**（形）と**SQLが読むテーブルの中身**（世代）の2つで決まる。
形は`cache_identity.shape_digest`が自動で署名するが、中身が作り直されたことを知っているのは
バッチが進める`derived_data_meta.revision`だけである。この2つを繋ぐのがここ。

**手で書く定数を持たない。** 手で書くと、上げ忘れ（古い値を配り続ける）と、バッチ完了後に
もう一度上げ直す必要（デプロイとバッチの間に配信されたタイルが、新しい鍵のまま古い値で
キャッシュへ載る）の両方が起きる。

世代はフロントへ`GET /api/axis-catalog`の応答で配る（較正値と同じ経路。起動時に1回取るものへ
相乗りさせ、取得を増やさない）。フロントはタイルURLのクエリへ入れてブラウザのキャッシュを
分ける。

世代そのものの読み直しと、変化したときにキャッシュを捨てる判断は
`derived_data_revision_service`が持つ（材料・スコア行列と同じ1箇所で決める）。ここはTTLを
持たず、読む前にその判断を促すだけ。

**促さずに読むと`x-`（まだ誰も読んでいない印）を配る。** 世代を読む経路はルート生成の
材料取得で、このカタログは起動直後に取られるため、促さない限り誰も読んでいない状態になる。
"""

from app.infrastructure.accident_repository import ACCIDENT_TILE_SHAPE
from app.infrastructure.cache_identity import tile_version
from app.infrastructure.road_graph_repository import POI_TILE_SHAPE, ROAD_SURFACE_TILE_SHAPE
from app.services import derived_data_revision_service

def served_tile_version(shape: str) -> str:
    """いま配信している世代（`<DBの世代>-<形の署名>`）。

    **ブラウザのURLへ入る値と、サーバー側のディスクキャッシュの鍵は同じ文字列にする。**
    形の署名だけを鍵にすると、SQLが同じままバッチが中身を作り直したとき（世代だけが動く）
    に鍵が変わらず、古い中身を配り続ける。
    """
    return tile_version(derived_data_revision_service.current_revision(), shape)


#: 配信するタイルの系統と、その形の署名。フロントが受け取る辞書のキーでもある。
TILE_SHAPES: dict[str, str] = {
    "road_surface": ROAD_SURFACE_TILE_SHAPE,
    "poi": POI_TILE_SHAPE,
    "accident": ACCIDENT_TILE_SHAPE,
}


async def current_tile_versions(repository) -> dict[str, str]:
    """系統名→配信する世代（`<DBの世代>-<形の署名>`）。

    `repository`はDBの世代を読める口（`get_derived_data_revision`）。`None`（DBなし構成）
    なら世代は不明のままにする。TTLの内側なら読み直さないため、リクエストごとに呼んでよい。
    """
    if repository is not None:
        await derived_data_revision_service.ensure_caches_match_db(repository)
    revision = derived_data_revision_service.current_revision()
    return {name: tile_version(revision, shape) for name, shape in TILE_SHAPES.items()}
