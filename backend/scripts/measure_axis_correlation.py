"""6軸（car_stress/accident/surface_q/stop_density/gradient/night）の軸間相関行列を
dev DBに対して計測する（改善計画T147、設計プロンプト「評価システムの層構造再設計」タスク8）。

`domain/registry.py: register_axis`の排他バリデータ（改善計画T137）は「同じ一次属性を
複数の軸が使っていないか」を登録時に機械的にチェックするが、異なる一次属性由来でも
結果的に相関してしまう間接的な相関まではチェックできない。本スクリプトはそれを
事後監視する（設計プロンプトの完了条件どおり|r|>0.7のペアを警告する）。

measure_axis_stats.py（T124の前例）と同じ「単発実行・結果を標準出力・単体テストつき」の
形式。scipy/numpy未導入のため相関計算は素朴なPython実装（pearson_correlationは
measure_axis_stats.pyと同じ実装をこのスクリプト内に複製する。private関数のモジュール
跨ぎimportを避ける既存方針、measure_axis_stats.py: _ACCIDENT_YEARS_COVERED_SQLの
docstring参照）。

**標本設計上の制約**: 標高（average_grade、gradient軸の入力）はRoad Graphへ恒久保存しない
設計のため（`elevation_attributes`テーブルは常時空、dev DB実測で確認済み。
docs/architecture.md「Road Graphへ恒久保存しない」参照）、国土地理院APIから区間ごとに
都度取得する必要がある。他5軸はDBのみで計算できる一方gradientだけ外部API依存という
非対称があるため、**6軸すべてを同一のランダムサンプル（road_edgesからN件）に対して計算し、
公平な相関比較にする**（5軸は全件・gradientだけ小標本、という統計的に歪んだ比較を避ける）。
サンプルサイズは既定300件（GSI APIへの負荷を抑えつつ相関係数が安定する規模。
キャッシュ済み地点はSQLite永続化キャッシュがヒットするため2回目以降の実行は高速）。

実行方法（backendディレクトリから）:
    .venv\\Scripts\\python.exe scripts\\measure_axis_correlation.py
    .venv\\Scripts\\python.exe scripts\\measure_axis_correlation.py --sample-size 500
    .venv\\Scripts\\python.exe scripts\\measure_axis_correlation.py --database-url <対象DB>
"""

import argparse
import asyncio
import sys
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402
from sqlalchemy import Text, bindparam, text  # noqa: E402
from sqlalchemy.dialects.postgresql import ARRAY  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

from app.config import settings  # noqa: E402
from app.domain.attributes import compute_elevation_attribute  # noqa: E402
from app.domain.difficulty import (  # noqa: E402
    accident_difficulty,
    gradient_difficulty,
    road_difficulty,
    stop_difficulty,
    car_stress_difficulty,
)
from app.domain.night import night_difficulty  # noqa: E402
from app.domain.recipe import ROAD_SUITABILITY_BASE_BY_HIGHWAY  # noqa: E402
from app.domain.road import classify_osm_surface  # noqa: E402
from app.domain.route import Coordinates  # noqa: E402
from app.domain.traffic import car_stress_level  # noqa: E402
from app.infrastructure.elevation_client import ElevationClient  # noqa: E402
from app.infrastructure.road_graph_repository import RoadGraphRepository  # noqa: E402
from app.services.evaluation_service import (  # noqa: E402
    load_motor_vehicle_density_recipe,
    load_road_suitability_recipe,
    load_car_stress_recipe,
)

AXIS_IDS = ["car_stress", "accident", "surface_q", "stop_density", "gradient", "night"]
CORRELATION_WARNING_THRESHOLD = 0.7
DEFAULT_SAMPLE_SIZE = 300
ELEVATION_CONCURRENCY = 5

# measure_axis_stats.pyと同じ対象highway集合（レシピが評価対象とするhighway）。
SCORED_HIGHWAYS: list[str] = sorted(ROAD_SUITABILITY_BASE_BY_HIGHWAY)

_SAMPLE_EDGES_SQL = text(
    """
    SELECT edge_id, highway, distance_m,
           ST_Y(ST_StartPoint(geom)) AS start_lat, ST_X(ST_StartPoint(geom)) AS start_lon,
           ST_Y(ST_EndPoint(geom)) AS end_lat, ST_X(ST_EndPoint(geom)) AS end_lon
    FROM road_edges
    WHERE highway = ANY(CAST(:highways AS text[]))
    ORDER BY random()
    LIMIT :sample_size
    """
).bindparams(bindparam("highways", type_=ARRAY(Text())))


# ---------------------------------------------------------------------------
# 純関数（DB/外部API I/Oから独立、単体テスト対象。test_measure_axis_correlation.py参照）
# ---------------------------------------------------------------------------


def pearson_correlation(xs: list[float], ys: list[float]) -> float | None:
    """Pearson相関係数（measure_axis_stats.pyと同じ実装、距離加重は本スクリプトでは
    不使用のため省略）。標本2件未満、分散0（全て同値）のときは相関が定義できないためNone。"""
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    covariance = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / n
    variance_x = sum((x - mean_x) ** 2 for x in xs) / n
    variance_y = sum((y - mean_y) ** 2 for y in ys) / n
    if variance_x <= 0 or variance_y <= 0:
        return None
    return covariance / (variance_x * variance_y) ** 0.5


def correlation_matrix(axis_values: dict[str, list[float | None]]) -> dict[tuple[str, str], float | None]:
    """axis_id→値リスト（Noneはデータ無し、リストの長さは全軸で揃っている＝同じ標本index）
    から、軸ペアごとのPearson相関を算出する。ペアごとに両軸とも値がある行だけを使う
    （軸によってNoneになる行が異なりうるため、ペアごとに有効行を絞り込む）。"""
    results: dict[tuple[str, str], float | None] = {}
    for axis_a, axis_b in combinations(axis_values, 2):
        pairs = [
            (a, b)
            for a, b in zip(axis_values[axis_a], axis_values[axis_b])
            if a is not None and b is not None
        ]
        xs = [a for a, _ in pairs]
        ys = [b for _, b in pairs]
        results[(axis_a, axis_b)] = pearson_correlation(xs, ys)
    return results


# ---------------------------------------------------------------------------
# DB/外部API I/O・オーケストレーション
# ---------------------------------------------------------------------------


async def _fetch_elevation_gradient(
    client: httpx.AsyncClient,
    elevation_client: ElevationClient,
    semaphore: asyncio.Semaphore,
    edge_id: str,
    start: Coordinates,
    end: Coordinates,
) -> float | None:
    async with semaphore:
        start_elev = await elevation_client.get_elevation(client, start)
        end_elev = await elevation_client.get_elevation(client, end)
    attribute = compute_elevation_attribute(edge_id, [start, end], [start_elev, end_elev], data_source="gsi")
    return attribute.average_grade


async def main(
    database_url: str | None = None, sample_size: int = DEFAULT_SAMPLE_SIZE, output_path: str | None = None
) -> int:
    # measure_axis_stats.pyと同じ理由でタイムアウト無しの専用エンジンを使う
    # （ORDER BY random()のフルスキャン＋複数のST_DWithin空間結合が既定20秒を超えうるため）。
    engine = create_async_engine(database_url or settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            rows = (
                await session.execute(_SAMPLE_EDGES_SQL, {"highways": SCORED_HIGHWAYS, "sample_size": sample_size})
            ).all()
            edge_ids = [row.edge_id for row in rows]

            repository = RoadGraphRepository(session)
            way_tags = await repository.get_way_tags(edge_ids)
            surface_attributes = await repository.get_surface_attributes(edge_ids)
            stop_counts = await repository.get_stop_poi_counts(edge_ids)
            intersection_counts = await repository.get_intersection_counts(edge_ids)
            accident_counts = await repository.get_accident_counts(edge_ids)
            accident_years_covered = await repository.get_accident_years_covered()
            designated_edge_ids = await repository.get_designated_edge_ids(edge_ids)
    finally:
        await engine.dispose()

    car_stress_recipe = load_car_stress_recipe()
    road_suitability_recipe = load_road_suitability_recipe()
    motor_vehicle_density_recipe = load_motor_vehicle_density_recipe()

    elevation_client = ElevationClient()
    semaphore = asyncio.Semaphore(ELEVATION_CONCURRENCY)
    async with httpx.AsyncClient(timeout=10.0) as http_client:
        gradients = await asyncio.gather(
            *(
                _fetch_elevation_gradient(
                    http_client,
                    elevation_client,
                    semaphore,
                    row.edge_id,
                    Coordinates(latitude=row.start_lat, longitude=row.start_lon),
                    Coordinates(latitude=row.end_lat, longitude=row.end_lon),
                )
                for row in rows
            )
        )

    axis_values: dict[str, list[float | None]] = {axis_id: [] for axis_id in AXIS_IDS}
    for row, gradient_percent in zip(rows, gradients):
        distance_km = row.distance_m / 1000 if row.distance_m else 0.0
        tags = way_tags.get(row.edge_id)
        is_designated = row.edge_id in designated_edge_ids

        level = (
            car_stress_level(
                row.highway, tags, is_designated, car_stress_recipe,
                road_suitability_recipe=road_suitability_recipe,
                motor_vehicle_density_recipe=motor_vehicle_density_recipe,
            )
            if tags is not None
            else None
        )
        axis_values["car_stress"].append(car_stress_difficulty(level))

        accident_count = accident_counts.get(row.edge_id)
        accident_per_km_year = (
            accident_count / distance_km / accident_years_covered
            if accident_count is not None and distance_km > 0 and accident_years_covered > 0
            else None
        )
        axis_values["accident"].append(accident_difficulty(accident_per_km_year))

        axis_values["surface_q"].append(road_difficulty(classify_osm_surface(surface_attributes.get(row.edge_id))))

        stop_count = stop_counts.get(row.edge_id)
        stop_count_per_km = stop_count / distance_km if stop_count is not None and distance_km > 0 else None
        intersection_count = intersection_counts.get(row.edge_id)
        intersection_count_per_km = (
            intersection_count / distance_km if intersection_count is not None and distance_km > 0 else None
        )
        axis_values["stop_density"].append(stop_difficulty(stop_count_per_km, intersection_count_per_km))

        axis_values["gradient"].append(gradient_difficulty(gradient_percent))
        axis_values["night"].append(night_difficulty(tags))

    matrix = correlation_matrix(axis_values)

    lines: list[str] = []
    lines.append(f"== 軸間相関行列（ピアソン、n={len(rows)}、road_edgesからのランダムサンプル） ==")
    coverage = {axis_id: sum(1 for v in values if v is not None) for axis_id, values in axis_values.items()}
    lines.append("軸別の有効値件数（None＝データ無しを除く）:")
    for axis_id in AXIS_IDS:
        lines.append(f"  {axis_id}: {coverage[axis_id]}/{len(rows)}")
    lines.append("")

    warnings: list[tuple[str, str, float]] = []
    for (axis_a, axis_b), r in sorted(matrix.items()):
        r_label = f"{r:.3f}" if r is not None else "N/A"
        flag = ""
        if r is not None and abs(r) > CORRELATION_WARNING_THRESHOLD:
            flag = f"  警告 |r|>{CORRELATION_WARNING_THRESHOLD}"
            warnings.append((axis_a, axis_b, r))
        lines.append(f"  {axis_a} × {axis_b}: r={r_label}{flag}")
    lines.append("")

    if warnings:
        lines.append(f"== 警告: |r|>{CORRELATION_WARNING_THRESHOLD}のペア（軸内係数の見直し課題として別タスク化を検討） ==")
        for axis_a, axis_b, r in warnings:
            lines.append(f"  {axis_a} × {axis_b}: r={r:.3f}")
    else:
        lines.append(f"すべてのペアで|r|<={CORRELATION_WARNING_THRESHOLD}（警告なし）")

    report = "\n".join(lines)
    print(report)

    if output_path is not None:
        Path(output_path).write_text(report + "\n", encoding="utf-8")
        print(f"\n（レポートを{output_path}へ書き出しました）")

    return 0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=None, help="計測対象DB（省略時はsettings.database_url）")
    parser.add_argument("--sample-size", type=int, default=DEFAULT_SAMPLE_SIZE, help="サンプルするEdge件数")
    parser.add_argument("--output", default=None, help="レポートを書き出すファイルパス（省略時は標準出力のみ）")
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args()
    sys.exit(asyncio.run(main(args.database_url, args.sample_size, args.output)))
