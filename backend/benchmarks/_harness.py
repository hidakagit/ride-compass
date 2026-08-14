"""time.perf_counterベースの軽量ベンチマーク計測ハーネス。

pytest-benchmark等の追加pip依存を増やさず、標準ライブラリだけで「実測値」
（min/median/mean/stdev）を出せるようにするための最小実装。ベンチマークの実行間で
GCが割り込むと1回だけ極端に遅いサンプルが混ざりやすいため、計測区間中はGCを止める
（`gc.disable`）。
"""

from __future__ import annotations

import asyncio
import gc
import statistics
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable


@dataclass
class BenchmarkResult:
    name: str
    n: int
    samples_s: list[float] = field(repr=False)
    note: str = ""

    @property
    def min_s(self) -> float:
        return min(self.samples_s)

    @property
    def median_s(self) -> float:
        return statistics.median(self.samples_s)

    @property
    def mean_s(self) -> float:
        return statistics.mean(self.samples_s)

    @property
    def stdev_s(self) -> float:
        return statistics.stdev(self.samples_s) if len(self.samples_s) > 1 else 0.0

    def format(self) -> str:
        note = f"  ({self.note})" if self.note else ""
        return (
            f"{self.name:<52} n={self.n:<5} "
            f"min={_fmt(self.min_s):>10}  median={_fmt(self.median_s):>10}  "
            f"mean={_fmt(self.mean_s):>10}  stdev={_fmt(self.stdev_s):>9}{note}"
        )


def _fmt(seconds: float) -> str:
    if seconds < 1e-3:
        return f"{seconds * 1e6:.1f} us"
    if seconds < 1:
        return f"{seconds * 1e3:.2f} ms"
    return f"{seconds:.3f} s"


def measure(name: str, fn: Callable[[], object], *, repeat: int = 20, warmup: int = 3, note: str = "") -> BenchmarkResult:
    """同期関数`fn`を`repeat`回計測する（引数無しのcallable、`lambda: f(x)`等で渡す）。"""
    for _ in range(warmup):
        fn()

    samples: list[float] = []
    gc_was_enabled = gc.isenabled()
    gc.disable()
    try:
        for _ in range(repeat):
            start = time.perf_counter()
            fn()
            samples.append(time.perf_counter() - start)
    finally:
        if gc_was_enabled:
            gc.enable()

    return BenchmarkResult(name=name, n=repeat, samples_s=samples, note=note)


def measure_async(
    name: str, coro_fn: Callable[[], Awaitable[object]], *, repeat: int = 20, warmup: int = 3, note: str = ""
) -> BenchmarkResult:
    """非同期関数`coro_fn`を単一のイベントループ内で`repeat`回計測する。

    毎回`asyncio.run`すると計測対象外のイベントループ生成コストが混ざるため、
    1つのイベントループを使い回すループを自前で回す。
    """

    async def _run() -> list[float]:
        for _ in range(warmup):
            await coro_fn()

        samples: list[float] = []
        gc_was_enabled = gc.isenabled()
        gc.disable()
        try:
            for _ in range(repeat):
                start = time.perf_counter()
                await coro_fn()
                samples.append(time.perf_counter() - start)
        finally:
            if gc_was_enabled:
                gc.enable()
        return samples

    samples = asyncio.run(_run())
    return BenchmarkResult(name=name, n=repeat, samples_s=samples, note=note)


def print_report(title: str, results: list[BenchmarkResult]) -> None:
    print(f"\n=== {title} ===")
    for r in results:
        print(r.format())
