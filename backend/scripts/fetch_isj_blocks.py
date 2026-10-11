r"""国土交通省の街区レベル位置参照情報（都道府県ごとの zip）を配布元から手元へ写す（取込とは分ける）。

取込はローカルのファイルを読むだけにする（`source_adapters/isj_block.py`）。

取るのは取込の範囲に掛かる都道府県の zip（1都道府県1つ）。都道府県はアドレス・ベース・レジストリの市区町村の代表点から
決める（`source_adapters/estat_small_area.py: range_prefectures`）ので、先に`scripts/fetch_abr.py`を流しておく。
取得の手順は`app.batch.common.fetch_verified`が持つ。どの版かはプロファイルが持つ（`isj_block`ソースの`rows.version`）。

実行方法（backendディレクトリから）:
    .venv\Scripts\python.exe scripts\fetch_isj_blocks.py
    .venv\Scripts\python.exe scripts\fetch_isj_blocks.py --profile path/to/profile.yaml
"""

import argparse
import logging
import sys
import zipfile
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.batch.common import fetch_verified
from app.batch.source_adapters.estat_small_area import range_prefectures
from app.batch.source_adapters.isj_block import DOWNLOAD_URL, archive_path, read_rows
from app.batch.source_profile import load_source_profile

logger = logging.getLogger("ridecompass.fetch_isj_blocks")

_REQUEST_TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=30.0)


def _readable(path: Path) -> bool:
    """CSV を1つ持つ zip で、見出しに街区符号・地番があり、1行以上あるか。"""
    try:
        rows = read_rows(path)
        first = next(rows, None)
        rows.close()
        return first is not None and "街区符号・地番" in first
    except (OSError, ValueError, zipfile.BadZipFile, UnicodeDecodeError):
        return False


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="街区レベル位置参照情報を手元へ写す")
    parser.add_argument("--profile", default=None, type=Path)
    args = parser.parse_args()

    profile = load_source_profile(args.profile)
    versions = sorted({spec.rows.version for spec in profile.sources if spec.adapter == "isj_block"})
    if not versions:
        logger.info("プロファイルに街区レベル位置参照情報の指定がありません")
        return 0
    prefectures = range_prefectures(profile)
    logger.info("範囲に掛かる都道府県: %s", ", ".join(prefectures))
    fetched = [
        fetch_verified(DOWNLOAD_URL.format(version=version, prefecture=code), archive_path(version, code), _readable,
                       timeout=_REQUEST_TIMEOUT, logger=logger)
        for version in versions for code in prefectures]
    return 0 if all(fetched) else 1


if __name__ == "__main__":
    from _stdio import use_utf8_stdio

    use_utf8_stdio()
    raise SystemExit(main())
