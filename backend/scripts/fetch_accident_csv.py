r"""警察庁の交通事故統計（本票CSV）を配布元から手元へ写す（取込とは分ける）。

取込はローカルのファイルを読むだけにする（`source_adapters/npa_honhyo.py`）。同じ形の
取得が標高（`fetch_dem_tiles.py`）・土地被覆（`fetch_lulc_raster.py`）・OSMの抽出ファイル
（`fetch_osm_pbf.py`）にある。

**何度実行しても安全で、終わる。**

- 手元にあって読めるファイルは落とし直さない
- 一時ファイルへ書いてから所定の名前へ移す。途中で落ちた半端なものを「取得済み」に
  見せない
- 落とし終えたら実際に開いてみる。開けなければ退けて失敗させる——読めないファイルを
  置いたまま成功を報告すると、次に落ちるのは取込の途中になる

どの年を要するかはプロファイルが持つ（`npa_honhyo`ソースの`rows.years`）。配布元のURLの
組み立て方だけがここにある。

実行方法（backendディレクトリから）:
    .venv\Scripts\python.exe scripts\fetch_accident_csv.py
    .venv\Scripts\python.exe scripts\fetch_accident_csv.py --profile path/to/profile.yaml
"""

import argparse
import csv
import logging
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.batch.source_adapters.npa_honhyo import DATA_DIR, ENCODING  # noqa: E402
from app.batch.source_profile import load_source_profile  # noqa: E402

logger = logging.getLogger("ridecompass.fetch_accident_csv")

#: 配布元。年ごとに1ファイル。
HONHYO_URL_TEMPLATE = (
    "https://www.npa.go.jp/publications/statistics/koutsuu/opendata/{year}/honhyo_{year}.csv")

#: 一時ファイルの印。所定の名前と紛れないもの。
PART_SUFFIX = ".part"

#: 落としたが開けなかったものを退ける先。消さないのは、開けない理由が壊れていることとは
#: 限らないため。
BROKEN_SUFFIX = ".broken"

REQUEST_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=30.0)


def honhyo_path(year: int) -> Path:
    """取込が読む置き場（`npa_honhyo.py`と同じ導き方）。"""
    return DATA_DIR / f"honhyo_{year}.csv"


def _readable(path: Path) -> bool:
    """本票として読めるか。大きさだけでは半端なファイルも配信元のエラーページも弾けない。"""
    try:
        with open(path, encoding=ENCODING, newline="") as f:
            reader = csv.DictReader(f)
            return bool(reader.fieldnames) and next(reader, None) is not None
    except (OSError, UnicodeDecodeError, csv.Error):
        return False


def _download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + PART_SUFFIX)
    written = 0
    with httpx.stream("GET", url, timeout=REQUEST_TIMEOUT, follow_redirects=True) as response:
        response.raise_for_status()
        with temporary.open("wb") as sink:
            for chunk in response.iter_bytes():
                sink.write(chunk)
                written += len(chunk)
    temporary.replace(destination)
    logger.info("取得した %s（%.1f MB）", destination.name, written / (1024 * 1024))


def fetch(years: list[int]) -> int:
    failures = 0
    for year in years:
        destination = honhyo_path(year)
        if destination.exists() and _readable(destination):
            logger.info("既にある %s", destination)
            continue
        url = HONHYO_URL_TEMPLATE.format(year=year)
        logger.info("取りに行く %s", url)
        _download(url, destination)
        if _readable(destination):
            continue
        broken = destination.with_name(destination.name + BROKEN_SUFFIX)
        destination.replace(broken)
        logger.error("落としたが読めない: %d年（%s へ退けた。もう一度実行すると取り直す）",
                     year, broken.name)
        failures += 1
    return failures


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="警察庁の本票CSVを手元へ写す")
    parser.add_argument("--profile", default=None, type=Path)
    args = parser.parse_args()

    profile = load_source_profile(args.profile)
    years = sorted({
        int(year) for spec in profile.sources if spec.adapter == "npa_honhyo"
        for year in (spec.rows.get("years") or [])
    })
    if not years:
        logger.info("プロファイルに本票CSVの年の指定がありません")
        return 0
    return 1 if fetch(years) else 0


if __name__ == "__main__":
    raise SystemExit(main())
