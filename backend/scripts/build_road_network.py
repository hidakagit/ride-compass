"""取込範囲全体の道路網の配列を作り、ディスクへ置く（`infrastructure/road_network_store.py`）。

今の派生データの世代・今のコードの形の置き場が既にあれば何もしない。デプロイの前処理が
旧コンテナを止める前に打つ——材料の式を変えたコードのデプロイでは作り直しに数分かかるが、
その間も旧コンテナが古い置き場で動き続ける。データを書くバッチ（`app/batch/`）の後は、
バッチの入口（`run_batch_cli`）が同じ処理を呼ぶ。

実行方法（backendディレクトリから）:
    .venv\\Scripts\\python.exe scripts\\build_road_network.py
"""

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.batch._common import batch_session_factory  # noqa: E402
from app.infrastructure import road_network_store  # noqa: E402


async def run() -> int:
    async with batch_session_factory(None) as session_factory:
        await road_network_store.ensure_current(session_factory)
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main())
