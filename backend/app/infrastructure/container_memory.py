"""このプロセスが入っているコンテナ（cgroup v2）のメモリ上限。"""

from pathlib import Path

CGROUP_MEMORY_MAX = Path("/sys/fs/cgroup/memory.max")


def memory_limit_bytes() -> int | None:
    """上限のバイト数。上限が付いていない（`max`）・cgroup v2の外（開発機）ならNone。"""
    try:
        text = CGROUP_MEMORY_MAX.read_text().strip()
    except OSError:
        return None
    return None if text == "max" else int(text)
