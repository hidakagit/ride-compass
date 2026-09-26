"""開発機のプロセス一覧（pid・親pid・実行ファイル名・コマンドライン）と、全体のCPU使用率。

定期確認（core.py）とスロットを温める処理の生死の判定（slots.py）が使う。飽和した機械へプロセスを
足さないため、外部コマンドを起こさずにプロセス内（psutil）で読む。道具の中でpsutilを読むのはこの
モジュールだけで、入っていないPythonでは、入れ方を示して止まる。
"""

from dataclasses import dataclass

try:
    import psutil
except ImportError:
    raise SystemExit("並行作業の道具に必要な部品（psutil）がこのPythonに入っていない。"
                     "入れ方: python -m pip install -r scripts/requirements.txt") from None


@dataclass
class Proc:
    pid: int
    ppid: int
    name: str
    #: 他のユーザーのプロセス等、権限が無くて読めないときはNone。
    cmdline: str | None


def processes() -> dict[int, Proc]:
    out = {}
    for p in psutil.process_iter(["ppid", "name", "cmdline"]):
        info = p.info
        cmdline = " ".join(info["cmdline"]) if info["cmdline"] else None
        out[p.pid] = Proc(p.pid, info["ppid"] or 0, info["name"] or "", cmdline)
    return out


def ancestors(procs: dict[int, Proc], pid: int) -> list[Proc]:
    out, seen = [], {pid}
    p = procs.get(pid)
    while p is not None and p.ppid not in seen:
        seen.add(p.ppid)
        p = procs.get(p.ppid)
        if p is not None:
            out.append(p)
    return out


def cpu_percent(sample: float) -> float:
    """機械全体のCPU使用率（`sample`秒の間の平均）。"""
    return psutil.cpu_percent(interval=sample)
