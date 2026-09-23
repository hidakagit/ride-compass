r"""2つの構成を並べ、**同じ入力に対する出力の差**を出す。

性能が良くなっても、出力が説明できない形で変わっていれば移行できない。DBやロジックを
入れ替えるたびに要る確認なので、その場で書かずここへ置く。

**完全一致は求めない。** 測り方や精度を変えれば値は動く。見るのは「差が設計変更で
説明できる大きさに収まっているか」で、**基準は呼び出し側が渡す**（`--tolerance`）。
基準を後から緩めると検証にならないため、先に決めて渡す。

比べるのは2つ:

- **軸の得点**（同じwayを指定して引く）。経路が変わると得点も変わるため、ルートの
  比較だけでは「ロジックの差」と「経路の差」を切り分けられない
- **ルートの候補**（同じ起点・距離）。方位ごとの距離を並べる

**この経路では標高由来の軸を比べられない。** 区間インスペクタは単独のwayを引くため、
勾配・風は`available=false`で返る（実機で確認）。標高の精度を変えた影響は、ルートの
比較か、別の口で見る必要がある。

実行方法（backendディレクトリから）:
    .venv\Scripts\python.exe -m benchmarks.bench_output_diff --old URL --new URL
"""

import argparse
import asyncio
import json
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from dataclasses import dataclass

from benchmarks._revision import announce_revision

#: 軸の得点の差が、この値を超えたら「説明を要する」として印を付ける。
DEFAULT_TOLERANCE = 1.0


def _post(base: str, path: str, body: dict) -> dict | None:
    request = urllib.request.Request(
        f"{base}{path}", method="POST", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None


def _get(base: str, path: str) -> dict | None:
    try:
        with urllib.request.urlopen(f"{base}{path}", timeout=60) as response:
            return json.load(response)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None


@dataclass
class AxisDiff:
    values: list[float]
    only_one_side: int


def compare_axes(old: str, new: str, way_ids: list[int], tolerance: float) -> None:
    diffs: dict[str, AxisDiff] = defaultdict(lambda: AxisDiff([], 0))
    both = 0
    for way_id in way_ids:
        o = _post(old, "/api/region/axis-inspector", {"osm_way_id": way_id})
        n = _post(new, "/api/region/axis-inspector", {"osm_way_id": way_id})
        if not o or not n:
            continue
        both += 1
        o_axes = {a["axis_id"]: a for a in o.get("axes", [])}
        n_axes = {a["axis_id"]: a for a in n.get("axes", [])}
        for axis_id in set(o_axes) | set(n_axes):
            a, b = o_axes.get(axis_id), n_axes.get(axis_id)
            if a is None or b is None:
                diffs[axis_id].only_one_side += 1
                continue
            if a["difficulty"] is None or b["difficulty"] is None:
                continue
            diffs[axis_id].values.append(b["difficulty"] - a["difficulty"])

    print(f"\n=== 軸の得点（同じwayで比較。両方で引けた {both}/{len(way_ids)}本）===")
    print(f"{'軸':<26} {'比較数':>6} {'一致':>6} {'平均差':>9} {'最大差':>9}  判定")
    for axis_id in sorted(diffs):
        d = diffs[axis_id]
        if not d.values:
            print(f"{axis_id:<26} {'—':>6} {'—':>6} {'':>9} {'':>9}  片方のみ{d.only_one_side}本")
            continue
        worst = max(d.values, key=abs)
        same = sum(1 for v in d.values if abs(v) < 1e-6)
        mark = "要説明" if abs(worst) > tolerance else "想定内"
        extra = f"  片方のみ{d.only_one_side}本" if d.only_one_side else ""
        print(f"{axis_id:<26} {len(d.values):>6} {same:>6} "
              f"{sum(d.values) / len(d.values):>+9.3f} {worst:>+9.3f}  {mark}{extra}")


async def compare_routes(old: str, new: str, latitude: float, longitude: float,
                         distance_km: float) -> None:
    async def generate(base: str) -> list[dict]:
        created = _post(base, "/api/routes/generate",
                        {"latitude": latitude, "longitude": longitude,
                         "distance_km": distance_km})
        if not created:
            return []
        for _ in range(120):
            await asyncio.sleep(5)
            status = _get(base, f"/api/routes/generate/{created['job_id']}")
            if not status or status["status"] not in ("running", "pending"):
                return ((status or {}).get("result") or {}).get("routes") or []
        return []

    old_routes, new_routes = await generate(old), await generate(new)
    print(f"\n=== ルートの候補（{latitude},{longitude} / {distance_km}km）===")
    print(f"候補数 旧 {len(old_routes)}件 / 新 {len(new_routes)}件")
    old_by = {r["direction_label"]: r for r in old_routes}
    new_by = {r["direction_label"]: r for r in new_routes}
    print(f"{'方位':<8} {'旧km':>8} {'新km':>8} {'差%':>8}")
    for direction in sorted(set(old_by) | set(new_by)):
        o, n = old_by.get(direction), new_by.get(direction)
        if o and n:
            pct = (n["distance_km"] - o["distance_km"]) / o["distance_km"] * 100
            print(f"{direction:<8} {o['distance_km']:>8.2f} {n['distance_km']:>8.2f} {pct:>+7.1f}%")
        else:
            row = o or n
            assert row is not None  # directionはどちらかの候補の方位から来る
            shown = row["distance_km"]
            side = "旧のみ" if o else "新のみ"
            print(f"{direction:<8} {shown:>8.2f} {'':>8} {side:>8}")


def main() -> int:
    parser = argparse.ArgumentParser(description="2つの構成の出力の差を出す")
    parser.add_argument("--old", required=True, help="比較元のURL")
    parser.add_argument("--new", required=True, help="比較先のURL")
    parser.add_argument("--ways", default="", help="比べるosm_way_id（カンマ区切り）")
    parser.add_argument("--latitude", type=float, default=35.685)
    parser.add_argument("--longitude", type=float, default=139.753)
    parser.add_argument("--distance-km", type=float, default=30.0)
    parser.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE,
                        help="軸の得点の差がこれを超えたら「要説明」と印を付ける")
    parser.add_argument("--skip-routes", action="store_true")
    args = parser.parse_args()

    announce_revision()
    if args.ways:
        compare_axes(args.old, args.new,
                     [int(w) for w in args.ways.split(",")], args.tolerance)
    else:
        print("（--ways が空のため軸の比較は行わない）", file=sys.stderr)
    if not args.skip_routes:
        asyncio.run(compare_routes(args.old, args.new, args.latitude,
                                   args.longitude, args.distance_km))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
