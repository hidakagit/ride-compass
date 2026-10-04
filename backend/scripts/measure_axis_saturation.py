"""公開軸ごとに、難易度が上端へ張り付いている延長の割合を測る。

軸の折れ点が実データの分布と合っていないと、難易度が全区間でほぼ同じ値になる。
そうなると重みをいくら上げてもルートが変わらない——**症状はエラーではなく
「重みが効かない」という無言の形**で出るため、ヘルスチェックにも例外にも現れない。

母集団・材料の組み立ては軸スタジオの分布プレビュー（`services/axis_preview_service.py`）
と同じで、違いは「折れ点を通す前の生値」ではなく**折れ点を通した後の難易度**を見る点。
飽和は折れ点の当て方の問題なので、生値の分布だけでは判断できない。

延長で重み付ける（本数で数えると短い道が多数を占め、実際に走る距離の感覚と合わない）。

**分布は地域で大きく変わる**ため、全域の平均だけを見ると市街地の偏りが消える。
`--bbox`で範囲を絞れば、その地域だけの分布を見られる（抽選は使わず範囲内を全件取る）。

実行方法（backendディレクトリから）:
    python scripts/measure_axis_saturation.py
    python scripts/measure_axis_saturation.py --axis stop_density --sample-percent 5
    python scripts/measure_axis_saturation.py --bbox 35.65,139.72,35.71,139.80
    python scripts/run_probe.py scripts/measure_axis_saturation.py --bbox 35.65,139.72,35.71,139.80   # 本番

抽選（`TABLESAMPLE`）は回ごとに違う標本を引く。同じ標本で前後を比べるなら`--bbox`で範囲を決める。
"""

import argparse
import asyncio
import os
import sys
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Literal

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.batch.common import batch_session_factory  # noqa: E402
from app.domain.axis_definitions import (  # noqa: E402
    AXIS_DEFINITIONS,
    evaluate_axes_inputs,
    evaluate_axes_values,
)
from app.domain.region import BoundingBox, parse_bbox  # noqa: E402
from app.infrastructure.road_graph_repository import RoadGraphRepository  # noqa: E402
from app.services import axis_preview_service  # noqa: E402
from app.services.axis_registry_service import refresh_axis_definitions  # noqa: E402
from app.infrastructure.axis_definition_repository import AxisDefinitionRepository  # noqa: E402

# 「上端へ張り付いている」とみなす難易度。100ちょうどに限ると、折れ点の最終区間に
# わずかに届かない値ばかりの軸を見逃す。
SATURATION_THRESHOLD = 95.0
# 同じ理由で下端も見る。全区間が0なら、その軸はルート選択へ何も寄与していない。
FLOOR_THRESHOLD = 5.0
# 上端・下端がこの割合以上を占める軸を張り付いているとみなす。
SATURATED_SHARE = 0.5
FLOORED_SHARE = 0.9

_QUANTILES = [("p10", 0.10), ("p50", 0.50), ("p90", 0.90), ("p99", 0.99)]

# 延長m・難易度・得点へ写す前の値（生値・分類の値）。
Row = tuple[float, float, object]
Cause = Literal["breakpoints", "single_value"]


def share_at_or_above(pairs: list[tuple[float, float]], threshold: float) -> float:
    """値が`threshold`以上である延長の割合。"""
    total_m = sum(m for m, _ in pairs)
    if total_m <= 0:
        return 0.0
    return sum(m for m, value in pairs if value >= threshold) / total_m


def share_at_or_below(pairs: list[tuple[float, float]], threshold: float) -> float:
    total_m = sum(m for m, _ in pairs)
    if total_m <= 0:
        return 0.0
    return sum(m for m, value in pairs if value <= threshold) / total_m


def largest_single_input_share(rows: list[Row], in_band: Callable[[float], bool] = lambda _: True) -> float:
    """難易度が`in_band`に入る道を得点へ写す前の値ごとにまとめ、最も長いまとまりが全延長に占める割合。"""
    total_m = sum(m for m, _, _ in rows)
    if total_m <= 0:
        return 0.0
    by_input: defaultdict[object, float] = defaultdict(float)
    for length_m, score, value in rows:
        if in_band(score):
            by_input[value] += length_m
    return max(by_input.values(), default=0.0) / total_m


def saturation_cause(rows: list[Row]) -> Cause | None:
    """張り付いていなければNone。張り付いた側の割合を1つの値だけで超えるなら`single_value`
    （同じ値の道はどの折れ点でも同じ難易度になり、散らない）、そうでなければ`breakpoints`。"""
    pairs = [(m, score) for m, score, _ in rows]
    bands: list[tuple[float, Callable[[float], bool], float]] = [
        (share_at_or_above(pairs, SATURATION_THRESHOLD), lambda s: s >= SATURATION_THRESHOLD, SATURATED_SHARE),
        (share_at_or_below(pairs, FLOOR_THRESHOLD), lambda s: s <= FLOOR_THRESHOLD, FLOORED_SHARE),
    ]
    for share, in_band, limit in bands:
        if share >= limit:
            return "single_value" if largest_single_input_share(rows, in_band) >= limit else "breakpoints"
    return None


async def run(
    database_url: str | None,
    axis_filter: str | None,
    sample_percent: float,
    limit: int,
    bbox: BoundingBox | None,
) -> int:
    async with batch_session_factory(database_url) as session_factory:
        async with session_factory() as session:
            # 軸定義はDBが唯一の正本。Python側に既定値は無いため先に読み込む。
            await refresh_axis_definitions(AxisDefinitionRepository(session))
            sample = await axis_preview_service.load_way_sample(
                RoadGraphRepository(session), sample_percent, limit, bbox)

    if not sample:
        print("サンプルが0件でした（道の生データが未取込か、--bboxの範囲に道が無い可能性）")
        return 1

    total_km = sum(m for m, _ in sample) / 1000.0
    scope = (
        f"TABLESAMPLE {sample_percent}%"
        if bbox is None
        else f"bbox {bbox.min_latitude},{bbox.min_longitude},"
             f"{bbox.max_latitude},{bbox.max_longitude}"
    )
    print(f"母集団: way {len(sample):,}本 / 総延長 {total_km:,.1f}km "
          f"({scope}, limit {limit:,})")
    print(f"{'軸':<28} {'算出率':>7} {'p10':>7} {'p50':>7} {'p90':>7} {'p99':>7}  上端／下端／最多の値")
    print("-" * 100)

    # 軸の階層（内部軸→公開軸）を解いて公開軸の難易度を得る。個々の軸へ
    # `evaluate_axis_values`を直接当てると、他の軸を材料にする合成軸が
    # 「材料が欠損」になってしまう。
    material_ids = {key for _, materials in sample for key in materials}
    columns = {key: [materials.get(key) for _, materials in sample] for key in material_ids}
    inputs = evaluate_axes_inputs(columns, len(sample))
    by_axis: dict[str, list[Row]] = {}
    for axis_id, scores in evaluate_axes_values(columns, len(sample)).items():
        by_axis[axis_id] = [
            (length_m, score, value)
            for (length_m, _), score, value in zip(sample, scores, inputs[axis_id])
            if score is not None
        ]

    causes: dict[Cause, list[str]] = {"breakpoints": [], "single_value": []}
    for axis_id in sorted(AXIS_DEFINITIONS):
        if not AXIS_DEFINITIONS[axis_id].is_published:
            continue
        if axis_filter is not None and axis_id != axis_filter:
            continue
        rows = by_axis.get(axis_id, [])
        pairs = [(m, score) for m, score, _ in rows]
        evaluated_m = sum(m for m, _ in pairs)
        evaluated_share = evaluated_m / sum(m for m, _ in sample)
        if not pairs:
            print(f"{axis_id:<28} {'0.0%':>7}  （全区間で材料が欠損）")
            continue
        q = axis_preview_service.weighted_quantiles(pairs, _QUANTILES, digits=1)
        high = share_at_or_above(pairs, SATURATION_THRESHOLD)
        low = share_at_or_below(pairs, FLOOR_THRESHOLD)
        print(
            f"{axis_id:<28} {evaluated_share:>6.1%} "
            f"{q['p10']:>7.1f} {q['p50']:>7.1f} {q['p90']:>7.1f} {q['p99']:>7.1f} "
            f" 上端{high:>5.1%} 下端{low:>5.1%} 最多の値{largest_single_input_share(rows):>5.1%}"
        )
        cause = saturation_cause(rows)
        if cause is not None:
            causes[cause].append(axis_id)

    print()
    print(f"上端 = 難易度{SATURATION_THRESHOLD:.0f}以上が占める延長の割合、"
          f"下端 = 難易度{FLOOR_THRESHOLD:.0f}以下が占める延長の割合、"
          "最多の値 = 得点へ写す前の値（生値・分類の値）が同じ道のうち最も長いまとまりの割合。")
    if causes["breakpoints"]:
        print(f"要注意（折れ点が分布と合っていない可能性）: {', '.join(causes['breakpoints'])}")
        print("折れ点の調整は軸スタジオ経由で行う（unpublish→PUT→republish）。")
    if causes["single_value"]:
        print("張り付いた側の大半が1つの値に集まっている（どの折れ点でも同じ難易度になり、折れ点では散らない。"
              f"実データどおりか、材料の側を見る）: {', '.join(causes['single_value'])}")
    if not any(causes.values()):
        print("上端・下端へ張り付いている軸はありません。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--axis", default=None, help="この軸だけを測る（既定: 公開軸すべて）")
    parser.add_argument("--sample-percent", type=float, default=2.0, help="TABLESAMPLEの抽選率")
    parser.add_argument("--limit", type=int, default=20_000, help="サンプルway数の上限")
    parser.add_argument(
        "--bbox", default=None,
        help="この範囲だけを測る（min_lat,min_lon,max_lat,max_lon。抽選は使わない）")
    parser.add_argument("--database-url", default=None, help="既定: 本番の調査の道具が渡す接続先、無ければ設定値")
    args = parser.parse_args()
    bbox = parse_bbox(args.bbox) if args.bbox else None
    database_url = args.database_url or os.environ.get("PROBE_DATABASE_URL")
    return asyncio.run(run(database_url, args.axis, args.sample_percent, args.limit, bbox))


if __name__ == "__main__":
    from _stdio import use_utf8_stdio

    use_utf8_stdio()
    raise SystemExit(main())
