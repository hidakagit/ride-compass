"""取込範囲全体の道路網の配列を作り、ディスクへ置く（`infrastructure/road_network_store.py`）。

今の派生データの世代・今のコードの形の置き場が既にあれば何もしない。デプロイの前処理が
旧コンテナを止める前に打つ——材料の式を変えたコードのデプロイでは作り直しに数分かかるが、
その間も旧コンテナが古い置き場で動き続ける。派生を作り直したときは、派生の入口
（`app/batch/derive_cli.py`）が作り直した表から作って置く。

実行方法（backendディレクトリから）:
    .venv\\Scripts\\python.exe scripts\\build_road_network.py
"""

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.batch.common import batch_session_factory
from app.infrastructure import road_network_store


async def run() -> int:
    async with batch_session_factory(None) as session_factory:
        await road_network_store.ensure_current(session_factory)
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main())
