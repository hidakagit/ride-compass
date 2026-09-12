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
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.config import settings  # noqa: E402
from app.domain.axis_definitions import AXIS_DEFINITIONS, evaluate_axes_scalar  # noqa: E402
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

_QUANTILES = [("p10", 0.10), ("p50", 0.50), ("p90", 0.90), ("p99", 0.99)]


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


async def run(
    axis_filter: str | None,
    sample_percent: float,
    limit: int,
    bbox: BoundingBox | None,
) -> int:
    engine = create_async_engine(settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            # 軸定義はDBが唯一の正本。Python側に既定値は無いため先に読み込む。
            await refresh_axis_definitions(AxisDefinitionRepository(session))
            sample = await axis_preview_service.load_way_sample(
                RoadGraphRepository(session), sample_percent, limit, bbox)
    finally:
        await engine.dispose()

    if not sample:
        print("サンプルが0件でした（way_attribute_countsの集計が未実行の可能性）")
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
    print(f"{'軸':<28} {'算出率':>7} {'p10':>7} {'p50':>7} {'p90':>7} {'p99':>7}  上端／下端")
    print("-" * 86)

    # 軸の階層（内部軸→公開軸）を解いて公開軸の難易度を得る。個々の軸へ
    # `evaluate_axis_scalar`を直接当てると、他の軸を材料にする合成軸（車の圧迫感）が
    # 「材料が欠損」になってしまう。
    by_axis: dict[str, list[tuple[float, float]]] = {}
    for length_m, materials in sample:
        scores, _ = evaluate_axes_scalar(materials)
        for axis_id, score in scores.items():
            if score is not None:
                by_axis.setdefault(axis_id, []).append((length_m, score))

    saturated: list[str] = []
    for axis_id in sorted(AXIS_DEFINITIONS):
        if not AXIS_DEFINITIONS[axis_id].is_published:
            continue
        if axis_filter is not None and axis_id != axis_filter:
            continue
        pairs = by_axis.get(axis_id, [])
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
            f" 上端{high:>5.1%} 下端{low:>5.1%}"
        )
        # 上端・下端のどちらかが大半を占める軸は、折れ点が実データの範囲と合っていない。
        if high >= 0.5 or low >= 0.9:
            saturated.append(axis_id)

    print()
    print(f"上端 = 難易度{SATURATION_THRESHOLD:.0f}以上が占める延長の割合、"
          f"下端 = 難易度{FLOOR_THRESHOLD:.0f}以下が占める延長の割合。")
    if saturated:
        print(f"要注意（折れ点が分布と合っていない可能性）: {', '.join(saturated)}")
        print("折れ点の調整は軸スタジオ経由で行う（unpublish→PUT→republish）。")
    else:
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
    args = parser.parse_args()
    bbox = parse_bbox(args.bbox) if args.bbox else None
    return asyncio.run(run(args.axis, args.sample_percent, args.limit, bbox))


if __name__ == "__main__":
    raise SystemExit(main())
