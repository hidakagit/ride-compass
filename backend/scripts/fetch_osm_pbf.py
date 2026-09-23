r"""OSMの抽出ファイル（`.pbf`）を配布元から手元へ写す（取込とは分ける）。

取込はローカルのファイルを読むだけにする。手で落とすと、置き場所と名前を間違えたまま
「取得済み」に見える。

取得の手順（読めるものは落とし直さない・一時ファイル経由・落とし終えたら開いてみる）は
`app.batch._common.fetch_verified`が持つ。読めないPBFを置いたまま成功を報告すると、
次に落ちるのは何時間もかかる取込の途中になる。

どのファイルを要するかはプロファイルが持つ（OSMを読むソースの`rows.file`）。配布元の
URLの組み立て方だけがここにある。

実行方法（backendディレクトリから）:
    .venv\Scripts\python.exe scripts\fetch_osm_pbf.py
    .venv\Scripts\python.exe scripts\fetch_osm_pbf.py --profile path/to/profile.yaml
"""

import argparse
import logging
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.batch._common import fetch_verified  # noqa: E402
from app.batch.source_adapters.osm_pbf import DATA_DIR  # noqa: E402
from app.batch.source_profile import load_source_profile  # noqa: E402

logger = logging.getLogger("ridecompass.fetch_osm_pbf")

#: 配布元。`{name}`は抽出ファイルの名前（`kanto-latest.osm.pbf`等）。
#: Geofabrikの日本の抽出は`asia/japan/`の下に地方ごとに置かれている。
PBF_URL = "https://download.geofabrik.de/asia/japan/{name}"

_REQUEST_TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=30.0)


def _readable(path: Path) -> bool:
    """osmiumが開けるか。

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


def _fetch(names: list[str]) -> int:
    return sum(
        not fetch_verified(PBF_URL.format(name=name), DATA_DIR / name, _readable,
                           timeout=_REQUEST_TIMEOUT, logger=logger)
        for name in names
    )


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="OSMの抽出ファイルを手元へ写す")
    parser.add_argument("--profile", default=None, type=Path)
    args = parser.parse_args()

    profile = load_source_profile(args.profile)
    # OSMを読むソースが指すファイル。同じファイルを複数のソースが指すので重複を除く。
    names = sorted({
        spec.rows.file for spec in profile.sources
        if spec.adapter.startswith("osm_pbf") and spec.rows.file
    })
    if not names:
        logger.info("プロファイルにOSMの抽出ファイルの指定がありません")
        return 0
    return 1 if _fetch(names) else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
