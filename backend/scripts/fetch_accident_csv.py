r"""警察庁の交通事故統計（本票CSV）を配布元から手元へ写す（取込とは分ける）。

取込はローカルのファイルを読むだけにする（`source_adapters/npa_honhyo.py`）。

取得の手順（読めるものは落とし直さない・一時ファイル経由・落とし終えたら開いてみる）は
`app.batch._common.fetch_verified`が持つ。

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

from app.batch._common import fetch_verified  # noqa: E402
from app.batch.source_adapters.npa_honhyo import ENCODING, honhyo_path  # noqa: E402
from app.batch.source_profile import load_source_profile  # noqa: E402

logger = logging.getLogger("ridecompass.fetch_accident_csv")

#: 配布元。年ごとに1ファイル。
HONHYO_URL_TEMPLATE = (
    "https://www.npa.go.jp/publications/statistics/koutsuu/opendata/{year}/honhyo_{year}.csv")

_REQUEST_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=30.0)


def _readable(path: Path) -> bool:
    """本票として読めるか（見出しと1行以上）。"""
    try:
        with open(path, encoding=ENCODING, newline="") as f:
            reader = csv.DictReader(f)
            return bool(reader.fieldnames) and next(reader, None) is not None
    except (OSError, UnicodeDecodeError, csv.Error):
        return False


def fetch(years: list[int]) -> int:
    return sum(
        not fetch_verified(HONHYO_URL_TEMPLATE.format(year=year), honhyo_path(year), _readable,
                           timeout=_REQUEST_TIMEOUT, logger=logger)
        for year in years
    )


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
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
