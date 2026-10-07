"""このプロセスが入っているコンテナ（cgroup v2）のメモリ上限。"""

from pathlib import Path

#: 本番の読み手はこのファイルだけだが、テストがディスク（プロセス境界）の置き場を差し替えて上限を与えるために公開する
#: （testing.md「確かめる高さ」の (c)）。
CGROUP_MEMORY_MAX = Path("/sys/fs/cgroup/memory.max")


def memory_limit_bytes() -> int | None:
    """上限のバイト数。上限が付いていない（`max`）・cgroup v2の外（開発機）ならNone。"""
    try:
        text = CGROUP_MEMORY_MAX.read_text().strip()
    except OSError:
        return None
    return None if text == "max" else int(text)
