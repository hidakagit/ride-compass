"""計測中に、DBとPython側で何が起きていたかを同じ実行から記録する。

所要時間だけでは「何が律速か」が分からない。壁時計が延びたとき、Python側がCPUを
使い切っているのか、DBの応答を待っているのか、どちらでもなく取り合っているのかで
打ち手が変わる。そして遅いのがDBなら、**どのクエリが**どんな**実行計画で**動いて
いたのかまで無いと、次の一手が決まらない。ここで全部取る。

psutilもpg_stat_statementsも使わない（依存と設定を増やさない）。自プロセスは
`resource.getrusage`、DB側は`pg_stat_activity`の標本から見る:

- **待ち事象が無い`active`**は、そのバックエンドがCPUを回していることを意味する
- **同じクエリが標本に現れた回数**は、そのクエリが占めた時間に比例する
- 実行計画は`EXPLAIN (GENERIC_PLAN)`で取る。値を束ねずに計画を出せるので、
  アプリが投げた文をそのまま渡せる

標本のクエリ文はPostgreSQLの設定（track_activity_query_size、既定1024バイト）で切られる。切られた文は
計画を取れないので、占めた割合だけを出して計画は空にする——推測で埋めない。
"""

import asyncio
import contextlib
import os
import re
import resource
import time
from collections import Counter
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import asyncpg

#: 標本を取る間隔（秒）。細かくするほど計測自体が対象へ割り込む。
DEFAULT_INTERVAL_SECONDS = 0.5

#: 実行計画まで取るクエリの数（占めた割合の大きい順）。
DEFAULT_PLAN_LIMIT = 3

_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class Sample:
    elapsed: float
    app_cpu_seconds: float
    app_rss_mb: float
    load1: float
    db_active: int
    db_on_cpu: int


@dataclass(frozen=True)
class QueryShare:
    """標本に現れた割合と、その文の実行計画。"""

    share: float
    samples: int
    query: str
    plan: str

    @property
    def head(self) -> str:
        return self.query[:110]


@dataclass
class ResourceTrace:
    samples: list[Sample] = field(default_factory=list)
    queries: Counter = field(default_factory=Counter)
    wall_seconds: float = 0.0
    query_plans: list[QueryShare] = field(default_factory=list)

    @property
    def app_cpu_seconds(self) -> float:
        if len(self.samples) < 2:
            return 0.0
        return self.samples[-1].app_cpu_seconds - self.samples[0].app_cpu_seconds

    @property
    def app_cpu_ratio(self) -> float:
        """壁時計に対してPython側がCPUを回していた割合。1.0で1コアぶん使い切り。"""
        return self.app_cpu_seconds / self.wall_seconds if self.wall_seconds else 0.0

    @property
    def peak_rss_mb(self) -> float:
        return max((s.app_rss_mb for s in self.samples), default=0.0)

    @property
    def db_cpu_ratio(self) -> float:
        """標本のうち、DBのバックエンドが待ち事象なしで動いていた割合。"""
        if not self.samples:
            return 0.0
        return sum(1 for s in self.samples if s.db_on_cpu > 0) / len(self.samples)

    @property
    def peak_load1(self) -> float:
        return max((s.load1 for s in self.samples), default=0.0)

    def as_dict(self) -> dict[str, object]:
        return {
            "wall_seconds": round(self.wall_seconds, 2),
            "app_cpu_seconds": round(self.app_cpu_seconds, 2),
            "app_cpu_ratio": round(self.app_cpu_ratio, 3),
            "db_cpu_ratio": round(self.db_cpu_ratio, 3),
            "peak_rss_mb": round(self.peak_rss_mb, 1),
            "peak_load1": round(self.peak_load1, 2),
            "sample_count": len(self.samples),
            "queries": [
                {"share": q.share, "samples": q.samples, "query": q.query, "plan": q.plan}
                for q in self.query_plans
            ],
        }

    def summary(self) -> str:
        return (
            f"壁時計 {self.wall_seconds:7.1f}秒 / "
            f"Python側CPU {self.app_cpu_seconds:6.1f}秒（{self.app_cpu_ratio:.2f}コア相当） / "
            f"DBがCPUを回していた標本 {self.db_cpu_ratio * 100:5.1f}% / "
            f"RSS最大 {self.peak_rss_mb:6.0f}MB / load最大 {self.peak_load1:.2f}"
        )

    def query_lines(self) -> list[str]:
        lines: list[str] = []
        for q in self.query_plans:
            lines.append(f"    {q.share * 100:5.1f}%（標本{q.samples}）{q.head}")
            for plan_line in q.plan.splitlines():
                lines.append(f"        {plan_line}")
            if not q.plan:
                lines.append("        （文が途中で切られているため計画を取れない）")
        return lines


def _load1() -> float:
    try:
        return os.getloadavg()[0]
    except OSError:
        return 0.0


def _rusage() -> tuple[float, float]:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    # Linuxの`ru_maxrss`はキロバイト。
    return usage.ru_utime + usage.ru_stime, usage.ru_maxrss / 1024


_ACTIVITY_SQL = """
SELECT state, wait_event, query
FROM pg_stat_activity
WHERE datname = current_database() AND pid <> pg_backend_pid() AND state = 'active'
"""


async def _explain(connection: asyncpg.Connection, query: str) -> str:
    """値を束ねずに計画を取る。取れない文（切られた文・ユーティリティ文）は空を返す。"""
    try:
        rows = await connection.fetch(f"EXPLAIN (GENERIC_PLAN) {query}")
    except (asyncpg.PostgresError, OSError):
        return ""
    return "\n".join(r[0] for r in rows)


@contextlib.asynccontextmanager
async def sample_resources(
    asyncpg_dsn: str,
    interval: float = DEFAULT_INTERVAL_SECONDS,
    plan_limit: int = DEFAULT_PLAN_LIMIT,
) -> AsyncIterator[ResourceTrace]:
    """囲んだ区間の資源の使われ方・DBが回していたクエリ・その実行計画を記録する。

    DBの標本は計測専用の接続から取る——計測対象の接続を借りると、計測自体が対象の
    待ち行列へ並んでしまう。
    """
    trace = ResourceTrace()
    connection = await asyncpg.connect(asyncpg_dsn)
    started = time.perf_counter()
    stop = asyncio.Event()

    async def loop() -> None:
        while not stop.is_set():
            try:
                rows = await connection.fetch(_ACTIVITY_SQL)
            except (asyncpg.PostgresError, OSError):
                rows = []
            on_cpu = sum(1 for r in rows if r["wait_event"] is None)
            for row in rows:
                text = _WHITESPACE.sub(" ", (row["query"] or "")).strip()
                if text:
                    trace.queries[text] += 1
            cpu_seconds, rss_mb = _rusage()
            trace.samples.append(Sample(
                elapsed=time.perf_counter() - started,
                app_cpu_seconds=cpu_seconds,
                app_rss_mb=rss_mb,
                load1=_load1(),
                db_active=len(rows),
                db_on_cpu=on_cpu,
            ))
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=interval)

    task = asyncio.create_task(loop())
    try:
        yield trace
    finally:
        trace.wall_seconds = time.perf_counter() - started
        stop.set()
        await task
        total = sum(trace.queries.values())
        for text, count in trace.queries.most_common(plan_limit):
            trace.query_plans.append(QueryShare(
                share=count / total if total else 0.0,
                samples=count,
                query=text,
                plan=await _explain(connection, text),
            ))
        await connection.close()
