"""住所の辞書（`jageocoder`用、街区まで・全国）を取得し、backendが開く置き場へ入れる。

`app.infrastructure.address_dictionary.DICTIONARY_DIR`が既にあれば、同じ置き場にある他の版を消すだけで終わる
（デプロイのたびに起動しても、2回目以降は存在を見るだけで終わる）。無ければ配布元のzipを落とし、一時の置き場へ入れ、
引けることを確かめてから`DICTIONARY_DIR`へ移し、zipは消す。

新しい版を入れた回は、他の版を消さない——デプロイはこのスクリプトを旧いコンテナを止める前に流し、旧いコンテナは
入れ替えまで旧い版を検索のたびに開く。旧い版は次に流したとき（入れ替えのあと）に消す。

置き場には、zipに同梱のREADME（利用条件）が辞書と一緒に入る——サーバへ置くときはREADMEを同じ場所に
置くことが利用条件である。

取得の手順（一時ファイル経由・落とし終えたら開いてみる）は`app.batch.common.fetch_verified`が持つ。

実行方法（backendディレクトリから）:
    .venv\\Scripts\\python.exe scripts\\fetch_address_dictionary.py
"""

import logging
import shutil
import sqlite3
import sys
import zipfile
from pathlib import Path

import httpx
import jageocoder

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.batch.common import fetch_verified  # noqa: E402
from app.domain.place_search import ADDRESS_DICTIONARY_URL  # noqa: E402
from app.infrastructure import address_dictionary  # noqa: E402

logger = logging.getLogger("ridecompass.fetch_address_dictionary")

#: 入れた辞書を確かめる入力。全国の辞書なので、都道府県の名前は必ず当たる。
PROBE_QUERY = "東京都"

_DOWNLOAD_TIMEOUT_SECONDS = 600.0


def _searchable(path: Path) -> bool:
    """入れた辞書を開いて引けるか。欠けたファイルの落ち方はファイルごとに違う（どれも`RuntimeError`の仲間か
    sqliteの例外）ので、1件引いてみる。"""
    try:
        return any(result.matched for result in address_dictionary.open_dictionary(path).searchNode(PROBE_QUERY))
    except (RuntimeError, sqlite3.Error) as exc:
        logger.error("入れた辞書を引けない %s error=%r", path, exc)
        return False


def _remove_other_versions(keep: Path) -> None:
    for path in keep.parent.iterdir():
        if path != keep:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            logger.info("他の版を消した %s", path.name)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    destination = address_dictionary.DICTIONARY_DIR
    if destination.exists():
        logger.info("既にある %s", destination)
        _remove_other_versions(destination)
        return 0

    archive = destination.with_name(destination.name + ".zip")
    try:
        if not fetch_verified(ADDRESS_DICTIONARY_URL, archive, zipfile.is_zipfile,
                              timeout=_DOWNLOAD_TIMEOUT_SECONDS, logger=logger):
            return 1
    except (httpx.HTTPError, OSError) as exc:
        logger.error("取得に失敗しました url=%s error=%r", ADDRESS_DICTIONARY_URL, exc)
        return 1

    installing = destination.with_name(destination.name + ".installing")
    jageocoder.install_dictionary(archive, db_dir=installing, skip_confirmation=True)
    if not _searchable(installing):
        return 1
    installing.rename(destination)
    archive.unlink()
    logger.info("辞書を入れた %s", destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
