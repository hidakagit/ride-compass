"""配信元が実データを持たないズームのJMAタイルを、親タイルから補間して作る。"""

from app.domain.jma_tile_specs import source_zoom_for_interpolation
from app.infrastructure.debug_log import log_throttled_warning
from app.infrastructure.jma_tile_client import EmptyTile, JmaTileClient
from app.infrastructure.jma_tile_interpolation import crop_and_upscale, crop_and_upscale_mvt, parse_tile_path


async def interpolated_tile(jma_tile_client: JmaTileClient, path: str) -> tuple[bytes, str] | None:
    """配信元が実データを持たないズームの要求に対し、親タイルから補間したタイルを返す。

    ラスタ（画像の拡大）・ベクタ（座標の変換）のどちらも対象で、戻り値は内容とContent-Type。
    対象外（実データがあるズーム・タイル以外のパス）・親が取れない・補間に失敗したときはNone。
    親タイルの取得は`JmaTileClient.get()`を通すため、Redisキャッシュ・レート制限・上流への
    秒間上限がそのまま効く。補間した結果をキャッシュへ書き戻すのは呼び出し元。

    Content-Typeは親タイルのものをそのまま使う（配信元が返す値と揃え、拡張子から
    推測しない）。
    """
    coords = parse_tile_path(path)
    if coords is None:
        return None
    if source_zoom_for_interpolation(coords.element, coords.z) is None:
        return None
    parent = await jma_tile_client.get(coords.parent_path())
    if parent is None or isinstance(parent, EmptyTile):
        # 親が空なら拡大しても空にしかならない。
        return None
    parent_content, parent_content_type = parent
    try:
        if coords.ext == "pbf":
            return crop_and_upscale_mvt(parent_content, coords.quadrant), parent_content_type
        return crop_and_upscale(parent_content, coords.quadrant), parent_content_type
    except Exception as exc:  # 補間の失敗で地図表示自体を落とさない
        log_throttled_warning(
            "jma:tile-interpolation",
            "JMAタイルの補間に失敗しました path=%s parent=%s error=%r",
            path,
            coords.parent_path(),
            exc,
        )
        return None
