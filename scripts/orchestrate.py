"""並行実行（司令塔）のコマンドの入口。中身は`scripts/orchestration/`にある。

    python scripts/orchestrate.py <サブコマンド> ...

使い方は`scripts/orchestration/core.py`の冒頭。`pending-backup`・`pending-inbox`・`priority`・`slot`・`ledger`は依頼で足した
別のモジュール（`scripts/orchestration/pending.py`・`queue.py`・`slots.py`・`ledger.py`）へ渡す——核はそれらを
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
    command = argv[i] if i < len(argv) else None
    if command in ("pending-backup", "pending-inbox", "priority", "slot", "ledger"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    if command in ("pending-backup", "pending-inbox"):
        from orchestration import pending

        return pending.main(argv)
    if command == "priority":
        from orchestration import queue

        return queue.main(argv)
    if command == "slot":
        from orchestration import slots

        return slots.main(argv[:i] + argv[i + 1:])
    if command == "ledger":
        from orchestration import ledger

        return ledger.main(argv[:i] + argv[i + 1:])
    return core.main(argv)


if __name__ == "__main__":
    sys.exit(main())
