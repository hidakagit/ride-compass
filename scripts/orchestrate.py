"""並行実行（司令塔）のコマンドの入口。中身は`scripts/orchestration/`にある。

    python scripts/orchestrate.py <サブコマンド> ...

使い方は`scripts/orchestration/core.py`の冒頭。`decision`・`queue`・`prereqs`・`priority`は依頼で
足した別のモジュール（`scripts/orchestration/decisions.py`・`queue.py`）へ渡す——核はそれらを
importしないため、振り分けはここで行う。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from orchestration import core


def main() -> int:
    argv = sys.argv[1:]
    # 全体の引数（--repo X・--dir X）の後ろにある最初のサブコマンドで振り分ける。
    i = 0
    while i < len(argv) and argv[i] in ("--repo", "--dir"):
        i += 2
    if argv[i:i + 1] == ["decision"]:
        from orchestration import decisions

        sys.stdout.reconfigure(encoding="utf-8")
        return decisions.main(argv[:i] + argv[i + 1:])
    if argv[i:i + 1] and argv[i] in ("queue", "prereqs", "priority"):
        from orchestration import queue

        sys.stdout.reconfigure(encoding="utf-8")
        return queue.main(argv)
    return core.main(argv)


if __name__ == "__main__":
    sys.exit(main())
