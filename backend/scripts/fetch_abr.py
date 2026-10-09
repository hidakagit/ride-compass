r"""アドレス・ベース・レジストリ（都道府県・市区町村・町字のテキストと位置参照拡張）を配布元から手元へ写す（取込とは分ける）。

取込はローカルのファイルを読むだけにする（`source_adapters/abr.py`）。

取るのは全国の1ファイルずつ（都道府県・市区町村・町字のテキストと、都道府県・市区町村の代表点）と、町字の代表点のうち
取込の範囲（`target.bbox`）に掛かる都道府県のもの（`source_adapters/abr.py: prefectures_in_range`。市区町村の代表点から
決めるので、市区町村の代表点を先に取る）。取得の手順（読めるものは落とし直さない・一時ファイル経由・落とし終えたら
開いてみる）は`app.batch.common.fetch_verified`が持つ。

置き場の名前はプロファイルの取った日（`abr`ソースの`rows.snapshot`）で決まる。取り直すときは日を変える。

実行方法（backendディレクトリから）:
    .venv\Scripts\python.exe scripts\fetch_abr.py
    .venv\Scripts\python.exe scripts\fetch_abr.py --profile path/to/profile.yaml
"""

import argparse
import logging
import sys
import zipfile
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.batch.common import fetch_verified  # noqa: E402
from app.batch.source_adapters.abr import (  # noqa: E402
    NATIONWIDE_ARCHIVES,
    archive_path,
    archive_url,
    prefectures_in_range,
    read_rows,
    town_position_stem,
)
from app.batch.source_profile import load_source_profile  # noqa: E402

logger = logging.getLogger("ridecompass.fetch_abr")

_REQUEST_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=30.0)


def _readable(path: Path) -> bool:
    """CSV を1つ持つ zip で、見出しが全国地方公共団体コードから始まり、1行以上あるか。"""
    try:
        rows = read_rows(path)
        first = next(rows, None)
        rows.close()
        return first is not None and "lg_code" in first
    except (OSError, ValueError, zipfile.BadZipFile, UnicodeDecodeError):
        return False


def _fetch(snapshot: str, stem: str) -> bool:
    return fetch_verified(archive_url(stem), archive_path(snapshot, stem), _readable,
                          timeout=_REQUEST_TIMEOUT, logger=logger)


def fetch(snapshot: str, bbox: tuple[float, float, float, float]) -> bool:
    if not all([_fetch(snapshot, stem) for stem in NATIONWIDE_ARCHIVES]):
        return False
    prefectures = prefectures_in_range(read_rows(archive_path(snapshot, "mt_city_pos_all")), bbox)
    logger.info("範囲に掛かる都道府県: %s", ", ".join(prefectures))
    return all([_fetch(snapshot, town_position_stem(code)) for code in prefectures])


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="アドレス・ベース・レジストリを手元へ写す")
    parser.add_argument("--profile", default=None, type=Path)
    args = parser.parse_args()

    profile = load_source_profile(args.profile)
    snapshots = sorted({spec.rows.snapshot for spec in profile.sources if spec.adapter == "abr"})
    if not snapshots:
        logger.info("プロファイルにアドレス・ベース・レジストリの指定がありません")
        return 0
    return 0 if all([fetch(snapshot, profile.target.bbox) for snapshot in snapshots]) else 1


if __name__ == "__main__":
    from _stdio import use_utf8_stdio

    use_utf8_stdio()
    raise SystemExit(main())
