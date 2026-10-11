r"""Overture Maps の地点（places）を配布元から手元へ写す（取込とは分ける）。

取込はローカルのファイルを読むだけにする（`source_adapters/overture_places.py`）。

配布は版ごとの GeoParquet で、全世界ぶんを AWS S3 に置いている。DuckDB で取込の範囲（`target.bbox`）の地点だけを
読み、列は全部のまま1つの Parquet へ書く（公式の文書「DuckDB」の読み方。S3 は認証なしで読める）。手順は
`app.batch.common.fetch_verified`と同じく、読めるものは取り直さず、一時ファイルへ書いてから所定の名前へ移し、
書き終えたら開いてみる。

どの版を要るかはプロファイルが持つ（`overture_places`ソースの`rows.release`）。

実行方法（backendディレクトリから）:
    .venv\Scripts\python.exe scripts\fetch_overture_places.py
    .venv\Scripts\python.exe scripts\fetch_overture_places.py --profile path/to/profile.yaml
"""

import argparse
import logging
import sys
import time
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.batch.common import FETCH_PART_SUFFIX, format_duration
from app.batch.source_adapters.overture_places import places_path
from app.batch.source_profile import load_source_profile

logger = logging.getLogger("ridecompass.fetch_overture_places")

#: 配布の置き場。版ごとに1つ。
PLACES_URL_TEMPLATE = "s3://overturemaps-us-west-2/release/{release}/theme=places/type=place/*"
_S3_REGION = "us-west-2"


def _readable(path: Path) -> bool:
    """Parquet として開け、1行以上あるか。"""
    try:
        with duckdb.connect() as conn:
            [(count,)] = conn.execute("SELECT count(*) FROM read_parquet(?)", [str(path)]).fetchall()
            return count > 0
    except duckdb.Error:
        return False


def fetch(release: str, bbox: tuple[float, float, float, float]) -> bool:
    destination = places_path(release)
    if destination.exists() and _readable(destination):
        logger.info("既にある %s", destination)
        return True
    url = PLACES_URL_TEMPLATE.format(release=release)
    logger.info("取りに行く %s", url)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + FETCH_PART_SUFFIX)
    min_lat, min_lon, max_lat, max_lon = bbox
    started = time.perf_counter()
    with duckdb.connect() as conn:
        conn.execute(f"SET s3_region = '{_S3_REGION}'")
        # 点の`bbox`の最小は点そのもの。`hive_partitioning`は置き場のパスの`theme=`・`type=`を列にする。
        conn.execute(
            "COPY (SELECT * FROM read_parquet(?, hive_partitioning = true)"
            " WHERE bbox.xmin BETWEEN ? AND ? AND bbox.ymin BETWEEN ? AND ?)"
            f" TO '{temporary}' (FORMAT parquet)",
            [url, min_lon, max_lon, min_lat, max_lat])
    if not _readable(temporary):
        temporary.unlink(missing_ok=True)
        logger.error("取り出した地点を開けない（範囲に地点が無いか、書き込みが壊れた）: %s", url)
        return False
    temporary.replace(destination)
    logger.info("置いた %s / %s", destination, format_duration(time.perf_counter() - started))
    return True


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="Overture Maps の地点を手元へ写す")
    parser.add_argument("--profile", default=None, type=Path)
    args = parser.parse_args()

    profile = load_source_profile(args.profile)
    releases = sorted({spec.rows.release for spec in profile.sources if spec.adapter == "overture_places"})
    if not releases:
        logger.info("プロファイルに Overture の地点の指定がありません")
        return 0
    return 0 if all(fetch(release, profile.target.bbox) for release in releases) else 1


if __name__ == "__main__":
    from _stdio import use_utf8_stdio

    use_utf8_stdio()
    raise SystemExit(main())
