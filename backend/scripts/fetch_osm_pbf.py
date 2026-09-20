r"""OSMの抽出ファイル（`.pbf`）を配布元から手元へ写す（取込とは分ける）。

取込はローカルのファイルを読むだけにする。同じ考え方の取得が標高（`fetch_dem_tiles.py`）
と土地被覆（`fetch_lulc_raster.py`）にあり、**OSMだけ口が無かった**ので手で落とす運用に
なっていた。手で落とすと、置き場所と名前を間違えたまま「取得済み」に見える。

**何度実行しても安全で、終わる。**

- 手元にあって読めるファイルは落とし直さない
- 一時ファイルへ書いてから所定の名前へ移す。途中で落ちた半端なものを「取得済み」に
  見せない
- 落とし終えたら実際に開いてみる。開けなければ消して失敗させる——読めないファイルを
  置いたまま成功を報告すると、次に落ちるのは何時間もかかる取込の途中になる

どのファイルを要するかはプロファイルが持つ（OSMを読むソースの`rows.file`）。配布元の
URLの組み立て方だけがここにある。

実行方法（backendディレクトリから）:
    .venv\Scripts\python.exe scripts\fetch_osm_pbf.py
    .venv\Scripts\python.exe scripts\fetch_osm_pbf.py --profile path/to/profile.yaml
"""

import argparse
import logging
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.batch._common import (  # noqa: E402
    PROGRESS_INTERVAL_SECONDS,
    format_duration,
    format_progress,
)
from app.batch.source_adapters.osm_pbf import DATA_DIR  # noqa: E402
from app.batch.source_profile import load_source_profile  # noqa: E402

logger = logging.getLogger("ridecompass.fetch_osm_pbf")

#: 配布元。`{name}`は抽出ファイルの名前（`kanto-latest.osm.pbf`等）。
#: Geofabrikの日本の抽出は`asia/japan/`の下に地方ごとに置かれている。
PBF_URL = "https://download.geofabrik.de/asia/japan/{name}"

#: 一時ファイルの印。所定の名前と紛れないもの。
PART_SUFFIX = ".part"

#: 落としたが開けなかったものを退ける先。消さないのは、開けない理由が壊れていること
#: とは限らないため。
BROKEN_SUFFIX = ".broken"

REQUEST_TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=30.0)


def _readable(path: Path) -> bool:
    """osmiumが開けるか。大きさだけでは半端なファイルを弾けない。

    **渡すのは、可能なら現在位置からの相対パス**——pyosmiumは非ASCIIを含む絶対パスの
    ファイルを開けない。絶対パスだけで試すと、中身が正しいファイルを壊れていると
    判定する。
    """
    import osmium

    candidates = [path]
    try:
        candidates.insert(0, path.relative_to(Path.cwd()))
    except ValueError:
        pass
    for candidate in candidates:
        try:
            reader = osmium.io.Reader(str(candidate))
        except (RuntimeError, OSError):
            continue
        reader.close()
        return True
    return False


def _download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + PART_SUFFIX)
    started = time.perf_counter()
    last_report = started
    written = 0
    with httpx.stream("GET", url, timeout=REQUEST_TIMEOUT, follow_redirects=True) as response:
        response.raise_for_status()
        total = int(response.headers.get("content-length") or 0) or None
        with temporary.open("wb") as sink:
            for chunk in response.iter_bytes():
                sink.write(chunk)
                written += len(chunk)
                now = time.perf_counter()
                if now - last_report < PROGRESS_INTERVAL_SECONDS:
                    continue
                last_report = now
                logger.info("取得中 %s", format_progress(
                    written // (1024 * 1024),
                    total // (1024 * 1024) if total else None,
                    now - started, "MB"))
    temporary.replace(destination)
    logger.info("取得した %s（%.0f MB / %s）", destination.name,
                written / (1024 * 1024), format_duration(time.perf_counter() - started))


def fetch(names: list[str]) -> int:
    failures = 0
    for name in names:
        destination = DATA_DIR / name
        if destination.exists() and _readable(destination):
            logger.info("既にある %s", destination)
            continue
        logger.info("取りに行く %s", PBF_URL.format(name=name))
        _download(PBF_URL.format(name=name), destination)
        if _readable(destination):
            continue
        # 読めないものを置いたまま成功を報告しない。ただし**消さずに退ける**——
        # 開けない理由は壊れているとは限らず、消すと落とし直しにまた時間を払う。
        broken = destination.with_name(destination.name + BROKEN_SUFFIX)
        destination.replace(broken)
        logger.error("落としたが開けない: %s（%s へ退けた。もう一度実行すると取り直す）",
                     name, broken.name)
        failures += 1
    return failures


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="OSMの抽出ファイルを手元へ写す")
    parser.add_argument("--profile", default=None, type=Path)
    args = parser.parse_args()

    profile = load_source_profile(args.profile)
    # OSMを読むソースが指すファイル。同じファイルを複数のソースが指すので重複を除く。
    names = sorted({
        str(spec.rows["file"]) for spec in profile.sources
        if spec.adapter.startswith("osm_pbf") and spec.rows.get("file")
    })
    if not names:
        logger.info("プロファイルにOSMの抽出ファイルの指定がありません")
        return 0
    return 1 if fetch(names) else 0


if __name__ == "__main__":
    raise SystemExit(main())
