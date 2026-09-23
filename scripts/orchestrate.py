"""並行実行（司令塔）のコマンドの入口。中身は`scripts/orchestration/`にある。

    python scripts/orchestrate.py <サブコマンド> ...

使い方は`scripts/orchestration/core.py`の冒頭。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from orchestration import core

if __name__ == "__main__":
    sys.exit(core.main())
