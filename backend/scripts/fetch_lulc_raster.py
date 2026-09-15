"""土地被覆ラスタ（Esri×Impact Observatory Sentinel-2 10m Annual LULC）を取得する。

`settings.lulc_raster_paths`（環境変数`LULC_RASTER_PATHS`）が指すファイルのうち、まだ
手元に無いものを配布元からダウンロードする。既にあるものには触らない（何度実行しても
安全。デプロイのたびに起動しても、2回目以降は数ミリ秒で終わる）。

取得元はAWS S3の公開バケット（サインなしで読める）。ファイル名はUTMゾーンと年
（例: `54S_2024.tif`）で、設定されたパスのファイル名部分をそのままバケット内のキーとして
使う——どのゾーン・どの年を使うかは設定側の決定で、このスクリプトは持たない。

ダウンロードは一時ファイルへ書いてから所定の名前へ移す。途中で落ちた半端なファイルが
「取得済み」に見えると、次の実行が再取得しないまま壊れたラスタを読み続けることになる。

実行方法（backendディレクトリから）:
    .venv\\Scripts\\python.exe scripts\\fetch_lulc_raster.py
"""

import logging
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.infrastructure.proj_data import pin_bundled_proj_data  # noqa: E402

pin_bundled_proj_data()

import rasterio  # noqa: E402
import rasterio.errors  # noqa: E402

logger = logging.getLogger("ridecompass.fetch_lulc_raster")

#: 配布元（docs/disaster-recovery.md）。`aws s3 cp --no-sign-request`と同じ内容を
#: HTTPSで取得する（認証もCLIも要らない）。
BUCKET_BASE_URL = "https://io-10m-annual-lulc.s3.us-west-2.amazonaws.com"

DOWNLOAD_TIMEOUT_SECONDS = 600.0


def download(url: str, destination: Path) -> None:
    temporary = destination.with_suffix(destination.suffix + ".part")
    destination.parent.mkdir(parents=True, exist_ok=True)
    downloaded = 0
    with httpx.stream("GET", url, timeout=DOWNLOAD_TIMEOUT_SECONDS, follow_redirects=True) as response:
        response.raise_for_status()
        with temporary.open("wb") as out:
            for chunk in response.iter_bytes():
                out.write(chunk)
                downloaded += len(chunk)
    # 取得できたものが本当にラスタかをここで確かめる。配布元がエラー本文を200で返した
    # 場合でも、サイズだけでは気づけない。
    try:
        with rasterio.open(temporary) as dataset:
            logger.info(
                "取得しました path=%s bytes=%d size=%dx%d crs=%s",
                destination,
                downloaded,
                dataset.width,
                dataset.height,
                dataset.crs,
            )
    except rasterio.errors.RasterioIOError:
        temporary.unlink(missing_ok=True)
        raise
    temporary.replace(destination)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    paths = settings.lulc_raster_paths_list
    if not paths:
        logger.warning(
            "LULC_RASTER_PATHSが未設定のため取得するものがありません"
            "（土地被覆の地図レイヤーは配信できない状態になります）"
        )
        return 0

    for raw_path in paths:
        destination = Path(raw_path)
        if destination.exists() and destination.stat().st_size > 0:
            logger.info("既にあります path=%s", destination)
            continue
        url = f"{BUCKET_BASE_URL}/{destination.name}"
        logger.info("取得します url=%s -> %s", url, destination)
        try:
            download(url, destination)
        except (httpx.HTTPError, OSError, rasterio.errors.RasterioIOError) as exc:
            logger.error("取得に失敗しました url=%s error=%r", url, exc)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
