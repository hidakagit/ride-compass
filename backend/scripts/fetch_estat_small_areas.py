r"""e-Stat の小地域の境界（国勢調査の町丁・字等、Shapefile）を配布元から手元へ写す（取込とは分ける）。

取込はローカルのファイルを読むだけにする（`source_adapters/estat_small_area.py`）。

取るのは取込の範囲に掛かる都道府県の zip（1都道府県1つ）。都道府県はアドレス・ベース・レジストリの市区町村の代表点から
決める（`source_adapters/estat_small_area.py: range_prefectures`）ので、先に`scripts/fetch_abr.py`を流しておく。
取得の手順は`app.batch.common.fetch_verified`が持つ。どの調査の境界かはプロファイルが持つ（`estat_small_area`ソースの
`rows.survey`）。

実行方法（backendディレクトリから）:
    .venv\Scripts\python.exe scripts\fetch_estat_small_areas.py
    .venv\Scripts\python.exe scripts\fetch_estat_small_areas.py --profile path/to/profile.yaml
"""

import argparse
import logging
import sys
import zipfile
from pathlib import Path

import httpx
import shapefile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.batch.common import fetch_verified
from app.batch.source_adapters.estat_small_area import (
    DOWNLOAD_URL,
    boundary_path,
    open_shapefile,
    range_prefectures,
)
from app.batch.source_profile import load_source_profile

logger = logging.getLogger("ridecompass.fetch_estat_small_areas")

_REQUEST_TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=30.0)


def _readable(path: Path) -> bool:
    """Shapefile を持つ zip で、1件以上の境界があるか。"""
    try:
        with zipfile.ZipFile(path) as archive:
            return len(open_shapefile(archive)) > 0
    except (OSError, KeyError, zipfile.BadZipFile, shapefile.ShapefileException):
        return False


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="e-Stat の小地域の境界を手元へ写す")
    parser.add_argument("--profile", default=None, type=Path)
    args = parser.parse_args()

    profile = load_source_profile(args.profile)
    surveys = sorted({spec.rows.survey for spec in profile.sources if spec.adapter == "estat_small_area"})
    if not surveys:
        logger.info("プロファイルに e-Stat の小地域の境界の指定がありません")
        return 0
    prefectures = range_prefectures(profile)
    logger.info("範囲に掛かる都道府県: %s", ", ".join(prefectures))
    fetched = [
        fetch_verified(DOWNLOAD_URL.format(survey=survey, prefecture=code), boundary_path(survey, code), _readable,
                       timeout=_REQUEST_TIMEOUT, logger=logger)
        for survey in surveys for code in prefectures]
    return 0 if all(fetched) else 1


if __name__ == "__main__":
    from _stdio import use_utf8_stdio

    use_utf8_stdio()
    raise SystemExit(main())
