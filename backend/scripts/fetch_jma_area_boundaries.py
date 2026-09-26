"""気象庁の「市町村等（気象警報等）」の区域の境界を取得し、backendが読む形で置く。

`app.infrastructure.jma_area_boundaries.BOUNDARY_PATH`が既にあれば何もしない（デプロイのたびに
起動しても、2回目以降は存在を見るだけで終わる）。無ければ配布元のzip（シェープファイル）を
落とし、区域ごとに境界を簡略化して書き、zipは消す。成功したら、同じ置き場にある他の版の
ファイルも消す。

区域のコードが空の図形（北方領土・帰属の決まっていない埋立地等。どの区域にも警報が出ない）は
書かない。

取得の手順（一時ファイル経由・落とし終えたら開いてみる）は`app.batch._common.fetch_verified`が
持つ。

実行方法（backendディレクトリから）:
    .venv\\Scripts\\python.exe scripts\\fetch_jma_area_boundaries.py
"""

import logging
import sys
import tempfile
import time
import zipfile
from collections import defaultdict
from pathlib import Path

import httpx
import shapefile
import shapely
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.batch._common import fetch_verified  # noqa: E402
from app.infrastructure import jma_area_boundaries  # noqa: E402

logger = logging.getLogger("ridecompass.fetch_jma_area_boundaries")

#: 境界を簡略化する許容誤差（度。おおむね10m）。元の境界は頂点が1,400万を超え、そのまま
#: 持つとbackendのメモリを数百MB使う。簡略化でできる隣の区域との隙間は、引く側が最寄りの
#: 区域へ寄せる（`jma_area_boundaries.NEAREST_LIMIT_DEG`）。
SIMPLIFY_TOLERANCE_DEG = 0.0001

_CODE_FIELD = "regioncode"
_DOWNLOAD_TIMEOUT_SECONDS = 600.0


def read_areas(archive_path: Path) -> dict[str, BaseGeometry]:
    """配布元のzipから、区域のコード→簡略化した境界を読む。"""
    with zipfile.ZipFile(archive_path) as archive, tempfile.TemporaryDirectory() as workdir:
        # 配布元のファイル名は日本語のため、手元では拡張子だけを残した名前で展開する。
        stem = Path(workdir) / "areas"
        for member in archive.namelist():
            suffix = Path(member).suffix.lower()
            if suffix in (".shp", ".shx", ".dbf"):
                stem.with_suffix(suffix).write_bytes(archive.read(member))
        with shapefile.Reader(str(stem), encoding="utf-8") as reader:
            parts: dict[str, list[BaseGeometry]] = defaultdict(list)
            for record in reader.iterShapeRecords():
                code = record.record.as_dict()[_CODE_FIELD]
                if code:
                    parts[code].append(shape(record.shape.__geo_interface__))
    return {
        code: shapely.simplify(
            geometries[0] if len(geometries) == 1 else shapely.union_all(geometries),
            SIMPLIFY_TOLERANCE_DEG, preserve_topology=True,
        )
        for code, geometries in parts.items()
    }


def _remove_other_versions(keep: Path) -> None:
    for path in keep.parent.iterdir():
        if path != keep:
            path.unlink()
            logger.info("他の版を消した %s", path.name)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    destination = jma_area_boundaries.BOUNDARY_PATH
    if destination.exists():
        logger.info("既にある %s", destination)
        _remove_other_versions(destination)
        return 0

    archive = destination.with_suffix(".zip")
    try:
        if not fetch_verified(jma_area_boundaries.SOURCE_URL, archive, zipfile.is_zipfile,
                              timeout=_DOWNLOAD_TIMEOUT_SECONDS, logger=logger):
            return 1
    except (httpx.HTTPError, OSError) as exc:
        logger.error("取得に失敗しました url=%s error=%r", jma_area_boundaries.SOURCE_URL, exc)
        return 1

    started = time.perf_counter()
    areas = read_areas(archive)
    jma_area_boundaries.write_boundaries(destination, areas)
    archive.unlink()
    logger.info("区域の境界を書いた %s areas=%d 頂点=%d 所要=%.0f秒", destination.name, len(areas),
                sum(shapely.get_num_coordinates(geometry) for geometry in areas.values()),
                time.perf_counter() - started)
    _remove_other_versions(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
