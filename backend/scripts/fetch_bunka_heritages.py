r"""国の指定・登録の文化財の建造物（文化遺産オンライン）を、ジャパンサーチの API から手元へ写す（取込とは分ける）。

取込はローカルのファイルを読むだけにする（`source_adapters/bunka_heritages.py`）。

**全国を取る**。取込の範囲は取込が絞るので、範囲を広げても取り直さない。口は全件取得（scroll）で、1回目に検索の条件を、
2回目からは応答の`scrollId`を渡し、`scrollId`の無い応答で終わる（公式の「簡易Web APIガイド」4.2.2。検索の口の
`from`・`size`は2,000件で止まる）。配信元は間を空けて打つよう求め、上限の目安を示さないので、1回ごとに
`_REQUEST_INTERVAL_SECONDS`待つ（同じガイドの1.4）。

手順は`app.batch.common.fetch_verified`と同じく、読めるものは取り直さず、一時ファイルへ書いてから所定の名前へ移す。
書き終えたら、行の数が応答の件数（`hit`）と合うかを見る——途中で打ち切られた一覧を取得済みに見せない。

置き場の名前はプロファイルの取った日（`bunka_heritages`ソースの`rows.snapshot`）で決まる。取り直すときは日を変える。

実行方法（backendディレクトリから）:
    .venv\Scripts\python.exe scripts\fetch_bunka_heritages.py
    .venv\Scripts\python.exe scripts\fetch_bunka_heritages.py --profile path/to/profile.yaml
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.batch.common import FETCH_PART_SUFFIX, format_duration  # noqa: E402
from app.batch.source_adapters.bunka_heritages import heritages_path  # noqa: E402
from app.batch.source_profile import load_source_profile  # noqa: E402

logger = logging.getLogger("ridecompass.fetch_bunka_heritages")

#: 全件取得の口。
SCROLL_URL = "https://jpsearch.go.jp/api/item/scroll/jps-cross"
#: 文化遺産オンラインの項目のうち、種類が建造物のもの。
SEARCH_PARAMS = {"f-db": "bunka", "f-type": "architecture"}

_REQUEST_INTERVAL_SECONDS = 1.0
_REQUEST_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=30.0)


def _readable(path: Path) -> bool:
    """1行1件の JSON として読め、1行以上あるか。"""
    try:
        with path.open(encoding="utf-8") as lines:
            first = lines.readline()
            return bool(first) and "id" in json.loads(first)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False


def fetch(snapshot: str) -> bool:
    destination = heritages_path(snapshot)
    if destination.exists() and _readable(destination):
        logger.info("既にある %s", destination)
        return True
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + FETCH_PART_SUFFIX)
    started = time.perf_counter()
    written = 0
    params: dict[str, str] = SEARCH_PARAMS
    with httpx.Client(timeout=_REQUEST_TIMEOUT) as client, temporary.open("w", encoding="utf-8") as sink:
        while True:
            response = client.get(SCROLL_URL, params=params)
            response.raise_for_status()
            page = response.json()
            for item in page["list"]:
                sink.write(json.dumps(item, ensure_ascii=False) + "\n")
            written += len(page["list"])
            hit = page["hit"]
            logger.info("取得中 %d / %d件", written, hit)
            if "scrollId" not in page or not page["list"]:
                break
            params = {"scrollId": page["scrollId"]}
            time.sleep(_REQUEST_INTERVAL_SECONDS)
    if written != hit or not _readable(temporary):
        temporary.unlink(missing_ok=True)
        logger.error("取り出した一覧が件数に合わない（%d件 / 応答の件数 %d件）。もう一度実行すると取り直す", written, hit)
        return False
    temporary.replace(destination)
    logger.info("置いた %s（%d件 / %s）", destination, written, format_duration(time.perf_counter() - started))
    return True


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="国の文化財の建造物を手元へ写す")
    parser.add_argument("--profile", default=None, type=Path)
    args = parser.parse_args()

    profile = load_source_profile(args.profile)
    snapshots = sorted({spec.rows.snapshot for spec in profile.sources if spec.adapter == "bunka_heritages"})
    if not snapshots:
        logger.info("プロファイルに文化財の建造物の指定がありません")
        return 0
    return 0 if all(fetch(snapshot) for snapshot in snapshots) else 1


if __name__ == "__main__":
    from _stdio import use_utf8_stdio

    use_utf8_stdio()
    raise SystemExit(main())
