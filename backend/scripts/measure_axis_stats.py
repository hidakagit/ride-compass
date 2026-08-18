"""軸ペア（交通ストレス×安全度）の相関・クランプ前生値分布・材料タグの補正発火率・
highway階級別事故密度を、dev DBに対して1コマンドで計測する（改善計画T124）。

measure_tag_coverage.py（T102の前例）と同じ「単発実行・結果を標準出力・単体テストつき」の
形式。相関測定・丸め損失・材料タグカバレッジの3分析は、T121（安全度と交通ストレスの独立性
検証）で使い捨てスクリプトとして実施したものを常設化したもの。DB I/Oから独立した純関数
（pearson_correlation/spearman_correlation/RoundingLossCounter/AdjustmentFiringCounter/
highway_accident_density）はtest_measure_axis_stats.pyで単体テストする。scipy/numpyは
未導入のため相関計算は素朴なPython実装。

事故密度は`highway`列を持つosm_raw_ways全体を対象にし、road_graph_repository.py:
_ACCIDENT_COUNTS_SQLと同じ30m・involves_bicycle・死亡事故重み付けパターンをhighway単位の
集計へ変えたSQLで計算する（GiST索引を使う`&&`前置フィルタも同じ）。designation該当は
designation_attributesをosm_way_idでDISTINCT JOINする（1つのWayがN10・N12両方に該当し
うるため）。レシピの判定ロジック自体はSQLで再実装せず、domain/traffic.py・domain/safety.py
の関数をway単位で直接呼び出す。

実行方法（backendディレクトリから）:
    .venv\\Scripts\\python.exe scripts\\measure_axis_stats.py
    .venv\\Scripts\\python.exe scripts\\measure_axis_stats.py --database-url <collect_jartic.pyで指定したDB>
"""

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import Float, Text, bindparam, text  # noqa: E402
from sqlalchemy.dialects.postgresql import ARRAY  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

from app.config import settings  # noqa: E402
from app.domain.accident import (  # noqa: E402
    ACCIDENT_FATAL_WEIGHT,
    ACCIDENT_MATCH_MAX_DISTANCE_M,
    distance_weighted_accident_density,
)
from app.domain.recipe import ROAD_SUITABILITY_BASE_BY_HIGHWAY  # noqa: E402
from app.domain.safety import SafetyBreakdown, safety_breakdown  # noqa: E402
from app.domain.traffic import (  # noqa: E402
    TrafficStressBreakdown,
    traffic_stress_breakdown,
)
from app.services.evaluation_service import (  # noqa: E402
    load_motor_vehicle_density_recipe,
    load_road_suitability_recipe,
    load_safety_recipe,
    load_traffic_stress_recipe,
)

# レシピが評価対象とするhighway（改善計画: 車との近さ材料の共有元化で交通ストレス・安全度は
# 同一のROAD_SUITABILITY_BASE_BY_HIGHWAYを参照するようになったため、unionを取るまでもなく
# 単一の集合になった）。
SCORED_HIGHWAYS: list[str] = sorted(ROAD_SUITABILITY_BASE_BY_HIGHWAY)

# クランプ範囲（domain/traffic.py: traffic_stress_breakdown・domain/safety.py:
# safety_breakdownにハードコードされている上下限のミラー。T122でdomain/recipe.pyへ
# clamp_levelプリミティブが共有化されたら、そちらから輸入する形へ置き換える）。
TRAFFIC_STRESS_CLAMP = (1, 5)
SAFETY_CLAMP = (1, 4)

# road_graph_repository.py: _ACCIDENT_YEARS_COVERED_SQLと同一（private定数のモジュール
# 跨ぎimportを避けるための複製。SQL自体は1行で保守コストが小さい）。
_ACCIDENT_YEARS_COVERED_SQL = text(
    "SELECT COUNT(DISTINCT occurred_year) FROM accident_import_runs WHERE status = 'succeeded'"
)

_WAY_ROWS_SQL = text(
    """
    SELECT w.highway, w.tags, ST_Length(w.geom::geography) / 1000.0 AS length_km,
           (d.osm_way_id IS NOT NULL) AS is_designated
    FROM osm_raw_ways w
    LEFT JOIN (SELECT DISTINCT osm_way_id FROM designation_attributes) d
        ON d.osm_way_id = w.osm_way_id
    WHERE w.highway = ANY(CAST(:highways AS text[]))
    """
).bindparams(bindparam("highways", type_=ARRAY(Text())))

# road_graph_repository.py: _ACCIDENT_COUNTS_SQLと同じ30m・involves_bicycle・死亡事故重み
# 付けパターンをhighway単位の集計へ変えたもの。scoped_waysで対象wayの長さを先に確定してから
# LEFT JOINすることで、事故が複数件マッチしたwayでも長さが重複加算されない。
_HIGHWAY_ACCIDENT_DENSITY_SQL = text(
    """
    WITH scoped_ways AS (
        SELECT osm_way_id, highway, geom, ST_Length(geom::geography) / 1000.0 AS length_km
        FROM osm_raw_ways
        WHERE highway = ANY(CAST(:highways AS text[]))
    ),
    way_accidents AS (
        SELECT w.osm_way_id,
               SUM(CASE WHEN a.accident_id IS NULL THEN 0 WHEN a.fatal THEN :fatal_weight ELSE 1 END)
                   AS weighted_count
        FROM scoped_ways w
        LEFT JOIN accident_points a
            ON a.geom && ST_Expand(w.geom, :max_distance_deg)
           AND ST_DWithin(a.geom::geography, w.geom::geography, :max_distance_m)
           AND a.involves_bicycle
        GROUP BY w.osm_way_id
    )
    SELECT w.highway, SUM(w.length_km) AS length_km, SUM(wa.weighted_count) AS weighted_count
    FROM scoped_ways w
    JOIN way_accidents wa ON wa.osm_way_id = w.osm_way_id
    GROUP BY w.highway
    """
).bindparams(
    bindparam("highways", type_=ARRAY(Text())),
    bindparam("fatal_weight", value=ACCIDENT_FATAL_WEIGHT, type_=Float()),
)


def _bbox_margin_deg(max_distance_m: float) -> float:
    """`&&`前置フィルタ用の緯度経度差(度)換算。road_graph_repository.py:
    _meters_to_bbox_margin_degと同じ換算式（1度=100,000mの保守的な近似）。private関数の
    モジュール跨ぎimportを避けるため1行だけここに複製する。"""
    return max_distance_m / 70_000.0


# ---------------------------------------------------------------------------
# 純関数（DB I/Oから独立、単体テスト対象。test_measure_axis_stats.py参照）
# ---------------------------------------------------------------------------


def pearson_correlation(xs: list[float], ys: list[float], weights: list[float] | None = None) -> float | None:
    """Pearson相関係数。weights指定時は距離加重版（加重平均・加重分散・加重共分散を使う）。
    scipy/numpy未導入のため素朴な実装。標本2件未満、分散0（全て同値）のときは相関が定義
    できないためNone。"""
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    if weights is None:
        weights = [1.0] * len(xs)
    total_weight = sum(weights)
    if total_weight <= 0:
        return None
    mean_x = sum(x * w for x, w in zip(xs, weights)) / total_weight
    mean_y = sum(y * w for y, w in zip(ys, weights)) / total_weight
    covariance = sum(w * (x - mean_x) * (y - mean_y) for x, y, w in zip(xs, ys, weights)) / total_weight
    variance_x = sum(w * (x - mean_x) ** 2 for x, w in zip(xs, weights)) / total_weight
    variance_y = sum(w * (y - mean_y) ** 2 for y, w in zip(ys, weights)) / total_weight
    if variance_x <= 0 or variance_y <= 0:
        return None
    return covariance / (variance_x * variance_y) ** 0.5


def _average_ranks(values: list[float]) -> list[float]:
    """同順位は平均順位にする（Spearman順位相関の標準的な扱い）。1始まりの順位を返す。"""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        average_rank = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = average_rank
        i = j + 1
    return ranks


def spearman_correlation(xs: list[float], ys: list[float], weights: list[float] | None = None) -> float | None:
    """Spearman順位相関。値を順位化してからpearson_correlationを適用する。距離加重版は
    加重Pearsonを順位に適用する簡便法（T121の使い捨て版と同じ手法）。"""
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    return pearson_correlation(_average_ranks(xs), _average_ranks(ys), weights)


def raw_pre_clamp_level(breakdown: TrafficStressBreakdown | SafetyBreakdown) -> int | None:
    """クランプ前の生値（base＋全`*_adjustment`フィールドの単純合計）。breakdownモデルの
    型を問わず動的にフィールドを拾うため、将来の補正追加でこの関数の変更は不要。
    motor_vehicle=no（motor_vehicle_no_override）はクランプの概念が無く常にlevel固定のため
    None（丸め損失の集計対象外）。base自体がNone（highway未登録）の場合もNone。"""
    if breakdown.base is None or breakdown.motor_vehicle_no_override:
        return None
    return breakdown.base + sum(
        value for name, value in breakdown.model_dump().items() if name.endswith("_adjustment")
    )


class RoundingLossCounter:
    """クランプ前生値がクランプ範囲の上限を超える/下限を下回る割合を、件数%・距離%の
    両方で集計する（改善計画T117/T121が段階数の判断に使った実測方法の常設化）。"""

    def __init__(self, clamp_min: int, clamp_max: int):
        self._min = clamp_min
        self._max = clamp_max
        self.total_count = 0
        self.total_distance_km = 0.0
        self.above_max_count = 0
        self.above_max_distance_km = 0.0
        self.below_min_count = 0
        self.below_min_distance_km = 0.0

    def add(self, raw: int, distance_km: float) -> None:
        self.total_count += 1
        self.total_distance_km += distance_km
        if raw > self._max:
            self.above_max_count += 1
            self.above_max_distance_km += distance_km
        if raw < self._min:
            self.below_min_count += 1
            self.below_min_distance_km += distance_km

    @staticmethod
    def _pct(numerator: float, denominator: float) -> float:
        return (numerator / denominator * 100) if denominator else 0.0

    def report_lines(self, label: str) -> list[str]:
        lines = [
            f"{label}（クランプ範囲{self._min}-{self._max}、対象{self.total_count}way・"
            f"{self.total_distance_km:.1f}km）:"
        ]
        lines.append(
            f"  上限超過(raw>{self._max}): {self.above_max_count}件"
            f"（{self._pct(self.above_max_count, self.total_count):.1f}%） / "
            f"{self.above_max_distance_km:.1f}km"
            f"（{self._pct(self.above_max_distance_km, self.total_distance_km):.1f}%）"
        )
        lines.append(
            f"  下限未満(raw<{self._min}): {self.below_min_count}件"
            f"（{self._pct(self.below_min_count, self.total_count):.1f}%） / "
            f"{self.below_min_distance_km:.1f}km"
            f"（{self._pct(self.below_min_distance_km, self.total_distance_km):.1f}%）"
        )
        return lines


def adjustment_field_names(breakdown_cls: type) -> list[str]:
    """Breakdownモデルの補正フィールド名（`*_adjustment`・`*_override`）を動的に拾う
    （新しい補正フィールドが増えてもAdjustmentFiringCounterの呼び出し側変更は不要）。"""
    return [
        name for name in breakdown_cls.model_fields if name.endswith("_adjustment") or name.endswith("_override")
    ]


class AdjustmentFiringCounter:
    """Breakdownの各補正フィールドが実際に発火した（0以外/True）割合を、件数%・距離%で
    集計する（改善計画T124: 材料タグカバレッジ、死に補正の検出。shoulder=0%のような
    矛盾を早期に出す）。"""

    def __init__(self, field_names: list[str]):
        self._fields = field_names
        self.total_count = 0
        self.total_distance_km = 0.0
        self.fired_count: dict[str, int] = dict.fromkeys(field_names, 0)
        self.fired_distance_km: dict[str, float] = dict.fromkeys(field_names, 0.0)

    def add(self, breakdown: TrafficStressBreakdown | SafetyBreakdown, distance_km: float) -> None:
        self.total_count += 1
        self.total_distance_km += distance_km
        dumped = breakdown.model_dump()
        for field in self._fields:
            value = dumped[field]
            fired = value if isinstance(value, bool) else value != 0
            if fired:
                self.fired_count[field] += 1
                self.fired_distance_km[field] += distance_km

    @staticmethod
    def _pct(numerator: float, denominator: float) -> float:
        return (numerator / denominator * 100) if denominator else 0.0

    def report_lines(self, label: str) -> list[str]:
        lines = [f"{label}（対象{self.total_count}way・{self.total_distance_km:.1f}km）:"]
        for field in sorted(self._fields, key=lambda f: -self.fired_count[f]):
            lines.append(
                f"  {field}: {self.fired_count[field]}件"
                f"（{self._pct(self.fired_count[field], self.total_count):.1f}%） / "
                f"{self.fired_distance_km[field]:.1f}km"
                f"（{self._pct(self.fired_distance_km[field], self.total_distance_km):.1f}%）"
            )
        return lines


def highway_accident_density(rows: list[tuple[str, float, float]], years_covered: int) -> dict[str, float | None]:
    """(highway, length_km合計, weighted_count合計)の行から、highwayごとの事故密度
    （自転車関与・件/(km・年)）を計算する。SQL側は集計のみ行い、密度の正規化計算自体は
    domain/accident.py: distance_weighted_accident_density（既存の距離加重集計、収録年数
    での正規化を含む）をそのまま再利用する（SQL側で再実装しない）。"""
    return {
        highway: distance_weighted_accident_density([(length_km, weighted_count)], years_covered)
        for highway, length_km, weighted_count in rows
    }


def _fmt(value: float | None, digits: int = 4) -> str:
    return f"{value:.{digits}f}" if value is not None else "N/A"


# ---------------------------------------------------------------------------
# DB I/O・オーケストレーション
# ---------------------------------------------------------------------------


async def fetch_way_rows(session: AsyncSession, highways: list[str]) -> list[Any]:
    result = await session.execute(_WAY_ROWS_SQL, {"highways": highways})
    return result.all()


async def fetch_highway_accident_density_rows(session: AsyncSession, highways: list[str]) -> list[Any]:
    result = await session.execute(
        _HIGHWAY_ACCIDENT_DENSITY_SQL,
        {
            "highways": highways,
            "max_distance_m": ACCIDENT_MATCH_MAX_DISTANCE_M,
            "max_distance_deg": _bbox_margin_deg(ACCIDENT_MATCH_MAX_DISTANCE_M),
        },
    )
    return result.all()


async def fetch_accident_years_covered(session: AsyncSession) -> int:
    result = await session.execute(_ACCIDENT_YEARS_COVERED_SQL)
    return result.scalar_one()


async def main(database_url: str | None = None) -> int:
    # infrastructure/database.py: get_engine()はWebリクエスト用にcommand_timeout=20秒を
    # 設定しており（長時間クエリを打ち切って空タイルへ劣化させる設計、同モジュール参照）、
    # 本スクリプトの集計クエリ（全way対象、dev DBで数万way規模）はこれを超えうるため、
    # app/batch/*.pyのバッチスクリプトと同じくタイムアウト無しの専用エンジンを使う。
    # collect_jartic.py/analyze_jartic_calibration.pyと同じ--database-urlで任意のDB
    # （較正検証時の本番Oracle等）へ向けられる。
    engine = create_async_engine(database_url or settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            way_rows = await fetch_way_rows(session, SCORED_HIGHWAYS)
            density_rows = await fetch_highway_accident_density_rows(session, SCORED_HIGHWAYS)
            years_covered = await fetch_accident_years_covered(session)
    finally:
        await engine.dispose()

    traffic_recipe = load_traffic_stress_recipe()
    safety_recipe = load_safety_recipe()
    # 交通ストレス・安全度が共有する「車との近さ」(N2)の材料（改善計画: 車との近さ材料の
    # 共有元化）。省略するとcar_closeness()がハードコードのDEFAULT_*へ静かにフォールバック
    # してしまい、road_suitability_recipe.yaml/motor_vehicle_density_recipe.yamlを編集して
    # 較正実験をしても反映されないため、traffic_recipe/safety_recipeと同様にYAMLから読む。
    road_suitability_recipe = load_road_suitability_recipe()
    motor_vehicle_density_recipe = load_motor_vehicle_density_recipe()

    traffic_levels: list[float] = []
    safety_levels: list[float] = []
    pair_distances: list[float] = []
    traffic_rounding = RoundingLossCounter(*TRAFFIC_STRESS_CLAMP)
    safety_rounding = RoundingLossCounter(*SAFETY_CLAMP)
    traffic_firing = AdjustmentFiringCounter(adjustment_field_names(TrafficStressBreakdown))
    safety_firing = AdjustmentFiringCounter(adjustment_field_names(SafetyBreakdown))

    for highway, tags, length_km, is_designated in way_rows:
        length_km = float(length_km)
        traffic = traffic_stress_breakdown(
            highway, tags, is_designated, traffic_recipe, road_suitability_recipe, motor_vehicle_density_recipe
        )
        safety = safety_breakdown(
            highway, tags, is_designated, safety_recipe, road_suitability_recipe, motor_vehicle_density_recipe
        )

        if traffic.level is not None:
            traffic_firing.add(traffic, length_km)
            raw = raw_pre_clamp_level(traffic)
            if raw is not None:
                traffic_rounding.add(raw, length_km)
        if safety.level is not None:
            safety_firing.add(safety, length_km)
            raw = raw_pre_clamp_level(safety)
            if raw is not None:
                safety_rounding.add(raw, length_km)
        if traffic.level is not None and safety.level is not None:
            traffic_levels.append(float(traffic.level))
            safety_levels.append(float(safety.level))
            pair_distances.append(length_km)

    density_by_highway = highway_accident_density(
        [(highway, float(length_km), float(weighted_count)) for highway, length_km, weighted_count in density_rows],
        years_covered,
    )

    print("== 軸ペア相関（交通ストレス × 安全度） ==")
    print(f"対象way数: {len(traffic_levels)}件・{sum(pair_distances):.1f}km")
    print(
        f"Pearson: {_fmt(pearson_correlation(traffic_levels, safety_levels))}"
        f"（距離加重: {_fmt(pearson_correlation(traffic_levels, safety_levels, pair_distances))}）"
    )
    print(
        f"Spearman: {_fmt(spearman_correlation(traffic_levels, safety_levels))}"
        f"（距離加重: {_fmt(spearman_correlation(traffic_levels, safety_levels, pair_distances))}）"
    )
    print()

    print("== クランプ前生値分布（丸め損失） ==")
    for line in traffic_rounding.report_lines("交通ストレス"):
        print(line)
    for line in safety_rounding.report_lines("安全度"):
        print(line)
    print()

    print("== 材料タグの補正発火率（死に補正の検出） ==")
    for line in traffic_firing.report_lines("交通ストレス"):
        print(line)
    for line in safety_firing.report_lines("安全度"):
        print(line)
    print()

    print(f"== highway階級別事故密度（自転車関与、重み付き、件/(km・年)、収録{years_covered}年） ==")
    for highway in sorted(density_by_highway, key=lambda h: -(density_by_highway[h] or 0)):
        print(f"  {highway}: {_fmt(density_by_highway[highway], digits=2)}")

    return 0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=None, help="計測対象DB（省略時はsettings.database_url）")
    return parser.parse_args(argv)


if __name__ == "__main__":
    sys.exit(asyncio.run(main(_parse_args().database_url)))
