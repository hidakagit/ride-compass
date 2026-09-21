r"""ルート生成を、1回の実行で判断に足るだけ測る。

**冷（初回）と温（2回目以降）を分けて出す。** キャッシュが空の初回は利用者が実際に
待つ時間で、暖機として捨ててよい値ではない。

**段の内訳はログから構造化して拾う。** 実装は`key=value`の形で段ごとの所要を出して
いるが、戻り値には載らない。目で読む代わりに機械が読める形へ移す。

**資源の推移も同じ実行で取る**（`_resources.py`）。壁時計が延びたときに、Python側が
CPUを使い切っているのか、DBを待っているのかを、後から測り直さずに言えるようにする。

構成を並べて比べるときは、**同じ引数で`DATABASE_URL`だけ変えて2回走らせる**。

実行方法（backendディレクトリから）:
    .venv\Scripts\python.exe -m benchmarks.bench_route_generation
    BENCH_RUNS=3 BENCH_LABEL=新構成 .venv\Scripts\python.exe -m benchmarks.bench_route_generation

環境変数:
    BENCH_ORIGIN       "緯度,経度"（既定は皇居）
    BENCH_DISTANCE_KM  周回の目標距離
    BENCH_RUNS         実行回数。1回目が冷、2回目以降が温
    BENCH_LABEL        出力に添える構成の名前
    BENCH_JSON         1なら最後に1行のJSONも出す（構成間の差分を機械で取るため）
"""

import asyncio
import json
import logging
import os
import re
import time

from app.batch._common import asyncpg_dsn
from app.config import settings
from app.domain.route import Coordinates
from app.domain.route_preference import RoutePreference
from benchmarks._resources import sample_resources
from benchmarks._revision import announce_revision
from benchmarks._route_generation_service import refresh_axis_registry, route_generator_session

#: 段の所要を出しているロガー。ここが出す`key=value`を拾う。
STAGE_LOGGERS = ("ridecompass.graph", "ridecompass.route_generator", "ridecompass.generate")

#: `key=value`。値に`[12.5,15.2]`のような括弧が来るため、空白までを値とする。
_FIELD = re.compile(r"(\w+)=([^\s]+)")

#: 先に並べる段。ここに無い段も**すべて**続けて出す——実装が段を増やしたときに、
#: 出力から黙って消えないようにする。
STAGE_ORDER = (
    "_build_search_materials_from_tile_cache",
    "_build_search_graph",
    "prepare",
    "turn_expanded_tree",
    "select_turnarounds",
    "compose_leg_costs",
)


def _is_number(value: object) -> bool:
    try:
        float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    return True


class _StageCapture(logging.Handler):
    """段ごとの`key=value`を拾って辞書へ積む。"""

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.stages: dict[str, dict[str, object]] = {}

    def emit(self, record: logging.LogRecord) -> None:
        """同じ段が何度も出る（脚ごと・タイルごと）。**上書きせず足し合わせる**
        ——上書きすると最後の1回だけが残り、全体で使った時間が消える。"""
        message = record.getMessage()
        name = message.split(" ", 1)[0]
        fields = dict(_FIELD.findall(message))
        if not fields:
            return
        seen = self.stages.setdefault(name, {})
        seen["回数"] = int(seen.get("回数", 0)) + 1
        for key, value in fields.items():
            if key.endswith("_ms") and _is_number(value):
                seen[key] = round(float(seen.get(key, 0.0)) + float(value), 1)
            else:
                seen[key] = value

    def reset(self) -> None:
        self.stages = {}


def _origin() -> Coordinates:
    raw = os.environ.get("BENCH_ORIGIN", "35.685,139.753")
    latitude, longitude = (float(part) for part in raw.split(","))
    return Coordinates(latitude=latitude, longitude=longitude)


def _stage_lines(stages: dict[str, dict[str, object]]) -> list[str]:
    """拾った段を全部出す。時間を持つ段は`秒`へ直して先頭へ置き、残りの値も添える。"""
    lines = []
    for name in (*STAGE_ORDER, *sorted(n for n in stages if n not in STAGE_ORDER)):
        fields = stages.get(name)
        if not fields:
            continue
        times = " ".join(
            f"{k[:-3]}={float(v) / 1000:.2f}秒" for k, v in fields.items()
            if k.endswith("_ms") and _is_number(v))
        others = " ".join(f"{k}={v}" for k, v in fields.items() if not k.endswith("_ms"))
        lines.append(f"    {name:<42} {times}" + (f"  [{others}]" if others else ""))
    return lines





async def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    capture = _StageCapture()
    for name in STAGE_LOGGERS:
        logger = logging.getLogger(name)
        logger.setLevel(logging.INFO)
        logger.addHandler(capture)

    announce_revision()
    label = os.environ.get("BENCH_LABEL", "構成")
    runs = int(os.environ.get("BENCH_RUNS", "2"))
    distance_km = float(os.environ.get("BENCH_DISTANCE_KM", "30"))
    origin = _origin()
    dsn = asyncpg_dsn(settings.database_url)

    print(f"\n=== {label} / {origin.latitude},{origin.longitude} / {distance_km}km / {runs}回 ===")
    records: list[dict[str, object]] = []

    await refresh_axis_registry()
    async with route_generator_session(RoutePreference()) as generator:
        for index in range(runs):
            capture.reset()
            kind = "冷" if index == 0 else "温"
            async with sample_resources(dsn) as trace:
                started = time.perf_counter()
                candidates = await generator.generate_loops(
                    origin, distance_km=distance_km, distance_tolerance_km=5.0)
                elapsed = time.perf_counter() - started
            print(f"\n  [{kind}] {elapsed:7.1f}秒 / 候補 {len(candidates)}件")
            print(f"    {trace.summary()}")
            print("  -- 段の内訳 --")
            for line in _stage_lines(capture.stages):
                print(line)
            print("  -- DBが回していたクエリと実行計画 --")
            for line in trace.query_lines():
                print(line)
            records.append({
                "label": label, "kind": kind, "run": index + 1,
                "seconds": round(elapsed, 2), "candidates": len(candidates),
                "resources": trace.as_dict(),
                "stages": capture.stages,
            })

    if os.environ.get("BENCH_JSON") == "1":
        print("\nJSON " + json.dumps(records, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
