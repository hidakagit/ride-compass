"""JARTIC実測交通量とtraffic_stress_level（LTS段階）の突き合わせ分析（改善計画T53）。

collect_jartic.py（同T53）がdev PostgreSQLへ収集した traffic_stations/traffic_hourly を、
最寄りのosm_raw_ways（30m以内、domain/road.py: SURFACE_MATCH_MAX_DISTANCE_Mと同じ許容量）へ
空間マッチし、そのway・タグからdomain/traffic.py: traffic_stress_breakdownでLTS段階を算出、
観測点の実測平均日交通量（上り+下り合算、収集日数で正規化）とLTS段階の関係を集計する。

このスクリプトが読む2テーブルはcollect_jartic.pyのdocstring通りdev専用（本番Oracle
migrationには含まれない）。

**既知の制約（2026-08-18実測）**: dev機PostgreSQLのosm_raw_waysは東京都心南部のみ
（実測extent: lon 139.61-139.87, lat 35.58-35.79）にしか投入されておらず、関東本土全域を
対象に収集したJARTIC観測点106件のうち、この範囲近傍（30m以内）にマッチするのはわずか8件に
とどまる（マッチ結果はhighway=primary/trunk相当のlevel4/5のみでlevel1-3のデータは無い）。
これはスクリプトの不具合ではなくdev DBのデータ投入範囲による構造的な制約で、より広い
LTS段階を横断した較正には本番相当（関東本土全域）のosm_raw_ways投入が必要
（現時点ではスコープ外）。

measure_axis_stats.py（T124）と同じくDB I/Oから独立した純関数
（group_volumes_by_level/summarize_group）はtest_analyze_jartic_calibration.pyで単体テスト
し、相関計算自体はmeasure_axis_stats.pyのpearson_correlation/spearman_correlationを
そのまま再利用する（同ロジックの複製を避ける。scripts/はパッケージ化していないが、
スクリプト直接実行時はPythonがそのファイルのディレクトリをsys.path[0]に自動追加するため、
同ディレクトリの兄弟モジュールを素朴にimportできる。tests/test_measure_axis_stats.pyの
sys.path.insert(scripts/)パターンと同じ前提）。

実行方法（backendディレクトリから）:
    .venv\\Scripts\\python.exe scripts\\analyze_jartic_calibration.py
    .venv\\Scripts\\python.exe scripts\\analyze_jartic_calibration.py --database-url <collect_jartic.pyで指定したDB>
"""

import argparse
import asyncio
import statistics
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import Text, bindparam, text  # noqa: E402
from sqlalchemy.dialects.postgresql import ARRAY  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

from app.config import settings  # noqa: E402
from app.domain.road import SURFACE_MATCH_MAX_DISTANCE_M  # noqa: E402
from app.domain.traffic import TRAFFIC_STRESS_BASE_BY_HIGHWAY, traffic_stress_level  # noqa: E402
from app.services.evaluation_service import load_traffic_stress_recipe  # noqa: E402

from measure_axis_stats import pearson_correlation, spearman_correlation  # noqa: E402

# traffic_stress_levelがNone以外を返すhighwayのみが対象（他はマッチしても評価不能なため
# 集計対象から自然に除外される）。
TRAFFIC_STRESS_HIGHWAYS: list[str] = sorted(TRAFFIC_STRESS_BASE_BY_HIGHWAY)

# 観測点→道路のマッチ許容距離。domain/road.py: SURFACE_MATCH_MAX_DISTANCE_Mと同じ
# 「物理的な道路網特徴へのスナップ許容量」を採用する（domain/traffic.py:
# INTERSECTION_MATCH_MAX_DISTANCE_Mのdocstringと同じ考え方）。
STATION_WAY_MATCH_MAX_DISTANCE_M = SURFACE_MATCH_MAX_DISTANCE_M

# 各観測点に最も近いwayを1件だけ選ぶLATERAL結合。designation該当はmeasure_axis_stats.py:
# _WAY_ROWS_SQLと同じくosm_way_idでDISTINCT JOIN（1つのWayがN10・N12両方に該当しうるため）。
# measure_axis_stats.py: _HIGHWAY_ACCIDENT_DENSITY_SQLと同じく、`&&`前置フィルタ
# （geometry型のGiST索引、osm_raw_ways.geomはspatial_index=True）でまず候補を絞ってから
# ST_DWithin(geography)で正確な距離判定をする。KNNの`<->`もgeometry型のまま使う
# （geographyへキャストするとGiST索引を使えず観測点ごとに全表スキャンになり実測で
# 極端に遅くなることを2026-08-18に確認済み）。
_STATION_WAY_MATCH_SQL = text(
    """
    SELECT s.station_id, w.highway, w.tags, (d.osm_way_id IS NOT NULL) AS is_designated
    FROM traffic_stations s
    JOIN LATERAL (
        SELECT osm_way_id, highway, tags, geom
        FROM osm_raw_ways
        WHERE highway = ANY(:highways)
          AND geom && ST_Expand(s.geom, :max_distance_deg)
          AND ST_DWithin(geom::geography, s.geom::geography, :max_distance_m)
        ORDER BY geom <-> s.geom
        LIMIT 1
    ) w ON true
    LEFT JOIN (SELECT DISTINCT osm_way_id FROM designation_attributes) d ON d.osm_way_id = w.osm_way_id
    """
).bindparams(bindparam("highways", type_=ARRAY(Text())))

# 観測点ごとの合計交通量（上り+下り込み）と収集日数。日数で割った1日あたり平均交通量を
# LTS段階との突き合わせに使う（収集日数が観測点間で揃っていなくても比較できるように
# 正規化する）。
_STATION_VOLUME_SQL = text(
    """
    SELECT station_id, SUM(volume) AS total_volume, COUNT(DISTINCT date(observed_at)) AS days_observed
    FROM traffic_hourly
    GROUP BY station_id
    """
)


def _bbox_margin_deg(max_distance_m: float) -> float:
    """`&&`前置フィルタ用の緯度経度差(度)換算。measure_axis_stats.py: _bbox_margin_deg・
    road_graph_repository.py: _meters_to_bbox_margin_degと同じ換算式（1度=100,000mの
    保守的な近似）。private関数のモジュール跨ぎimportを避けるため1行だけここに複製する。"""
    return max_distance_m / 70_000.0


# ---------------------------------------------------------------------------
# 純関数（DB I/Oから独立、単体テスト対象。test_analyze_jartic_calibration.py参照）
# ---------------------------------------------------------------------------


def group_volumes_by_level(rows: list[tuple[int | None, float]]) -> dict[int, list[float]]:
    """(traffic_stress_level, 1日あたり平均交通量)の列を、level別のリストへ束ねる。
    level=None（highway未登録・マッチ失敗）は集計対象外。"""
    grouped: dict[int, list[float]] = {}
    for level, volume in rows:
        if level is None:
            continue
        grouped.setdefault(level, []).append(volume)
    return grouped


def summarize_group(volumes: list[float]) -> dict[str, float | int]:
    """1つのLTS段階内の交通量分布サマリ（件数・平均・中央値・最小・最大）。"""
    return {
        "count": len(volumes),
        "mean": statistics.fmean(volumes),
        "median": statistics.median(volumes),
        "min": min(volumes),
        "max": max(volumes),
    }


def is_monotonic_by_level(grouped: dict[int, list[float]], key: str = "mean") -> bool:
    """level昇順に集計値（既定: 平均交通量）が単調非減少かどうか。T53完了条件
    「LTS段階間で交通量分布が単調に分離しているか」の機械判定用。"""
    levels = sorted(grouped)
    if len(levels) < 2:
        return True
    values = [summarize_group(grouped[level])[key] for level in levels]
    return all(values[i] <= values[i + 1] for i in range(len(values) - 1))


def _fmt(value: float | None, digits: int = 1) -> str:
    return f"{value:.{digits}f}" if value is not None else "N/A"


# ---------------------------------------------------------------------------
# DB I/O・オーケストレーション
# ---------------------------------------------------------------------------


async def fetch_station_way_matches(session: AsyncSession) -> list[Any]:
    result = await session.execute(
        _STATION_WAY_MATCH_SQL,
        {
            "highways": TRAFFIC_STRESS_HIGHWAYS,
            "max_distance_m": STATION_WAY_MATCH_MAX_DISTANCE_M,
            "max_distance_deg": _bbox_margin_deg(STATION_WAY_MATCH_MAX_DISTANCE_M),
        },
    )
    return result.all()


async def fetch_station_volumes(session: AsyncSession) -> dict[int, float]:
    result = await session.execute(_STATION_VOLUME_SQL)
    return {row.station_id: float(row.total_volume) / row.days_observed for row in result.all()}


async def main(database_url: str | None = None) -> int:
    # measure_axis_stats.pyと同じ理由（get_engine()の20秒command_timeoutはWebリクエスト用で
    # 本スクリプトの集計クエリには短すぎうる）でタイムアウト無しの専用エンジンを使う。
    # collect_jartic.pyの--database-urlと同じく、既定はsettings.database_url（dev機）だが
    # 引数で任意のDB（較正検証時の本番Oracle等）へ向けられる。
    engine = create_async_engine(database_url or settings.database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            matches = await fetch_station_way_matches(session)
            volume_by_station = await fetch_station_volumes(session)
    finally:
        await engine.dispose()

    if not matches:
        print("観測点にマッチするwayが見つかりませんでした（traffic_stationsが空、または")
        print(f"半径{STATION_WAY_MATCH_MAX_DISTANCE_M:.0f}m以内に対象highwayが無い可能性）。")
        return 1

    recipe = load_traffic_stress_recipe()
    level_volume_rows: list[tuple[int | None, float]] = []
    unmatched_volume_stations = 0
    for station_id, highway, tags, is_designated in matches:
        volume = volume_by_station.get(station_id)
        if volume is None:
            unmatched_volume_stations += 1
            continue
        level = traffic_stress_level(highway, tags, is_designated, recipe)
        level_volume_rows.append((level, volume))

    if unmatched_volume_stations:
        print(f"注意: {unmatched_volume_stations}件の観測点はway最寄りマッチはあるが交通量データ無し（スキップ）")

    grouped = group_volumes_by_level(level_volume_rows)
    levels = [float(level) for level, _ in level_volume_rows if level is not None]
    volumes = [volume for level, volume in level_volume_rows if level is not None]

    print("== JARTIC実測交通量 × traffic_stress_level（LTS段階）突き合わせ（改善計画T53） ==")
    print(f"マッチ観測点数: {len(matches)}件（うち交通量データありlevel算出成功: {len(level_volume_rows)}件）")
    print()

    print("== LTS段階別の1日あたり平均交通量分布（台/日、上り+下り合算） ==")
    for level in sorted(grouped):
        summary = summarize_group(grouped[level])
        print(
            f"  level={level}: {summary['count']}観測点 "
            f"平均={_fmt(summary['mean'])} 中央値={_fmt(summary['median'])} "
            f"最小={_fmt(summary['min'])} 最大={_fmt(summary['max'])}"
        )
    print()

    monotonic = is_monotonic_by_level(grouped)
    print(f"単調性（level昇順で平均交通量が単調非減少か）: {'YES' if monotonic else 'NO'}")
    print(
        f"Pearson相関（level×交通量）: {_fmt(pearson_correlation(levels, volumes), digits=3)}"
    )
    print(
        f"Spearman順位相関（level×交通量）: {_fmt(spearman_correlation(levels, volumes), digits=3)}"
    )

    return 0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=None, help="分析対象DB（省略時はsettings.database_url）")
    return parser.parse_args(argv)


if __name__ == "__main__":
    sys.exit(asyncio.run(main(_parse_args().database_url)))
