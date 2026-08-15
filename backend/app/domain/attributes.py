from datetime import datetime, timezone

from pydantic import BaseModel

from app.domain.geo import haversine_distance_km
from app.domain.graph import RoadGraph
from app.domain.route import Coordinates


class ElevationAttribute(BaseModel):
    """Edgeへ紐付ける標高属性（仕様書15章）。Edge本体（domain/graph.py）とは独立して保持する。

    average_grade/max_grade/min_gradeは符号付き（登り=正、下り=負）。
    有効な標高が2点未満の場合は全フィールドNoneのまま返す（Road Graph移行前のルート単位評価と同じ
    「取得失敗は握りつぶしてnull」方針、docs/architecture.md「標高計算のアルゴリズムと
    既知の制約」参照）。
    """

    edge_id: str
    start_elevation_m: float | None = None
    end_elevation_m: float | None = None
    elevation_gain_m: float | None = None
    elevation_loss_m: float | None = None
    average_grade: float | None = None
    max_grade: float | None = None
    min_grade: float | None = None
    data_source: str
    data_version: str | None = None
    calculated_at: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def compute_elevation_attribute(
    edge_id: str,
    points: list[Coordinates],
    elevations: list[float | None],
    data_source: str,
) -> ElevationAttribute:
    """Edgeの形状点列とそれぞれの標高値からElevationAttributeを算出する。

    標高が取得できなかった点（None）は除外して評価する（Road Graph移行前のルート単位評価と同じ方針）。
    """
    valid = [(p, e) for p, e in zip(points, elevations) if e is not None]
    if len(valid) < 2:
        return ElevationAttribute(edge_id=edge_id, data_source=data_source, calculated_at=_now_iso())

    gain = 0.0
    loss = 0.0
    max_grade: float | None = None
    min_grade: float | None = None
    total_distance_m = 0.0

    for (p1, e1), (p2, e2) in zip(valid, valid[1:]):
        diff = e2 - e1
        if diff > 0:
            gain += diff
        else:
            loss += -diff

        distance_m = haversine_distance_km(p1, p2) * 1000
        total_distance_m += distance_m
        if distance_m > 0:
            grade = diff / distance_m * 100
            max_grade = grade if max_grade is None else max(max_grade, grade)
            min_grade = grade if min_grade is None else min(min_grade, grade)

    start_elevation = valid[0][1]
    end_elevation = valid[-1][1]
    average_grade = (end_elevation - start_elevation) / total_distance_m * 100 if total_distance_m > 0 else None

    return ElevationAttribute(
        edge_id=edge_id,
        start_elevation_m=round(start_elevation, 1),
        end_elevation_m=round(end_elevation, 1),
        elevation_gain_m=round(gain, 1),
        elevation_loss_m=round(loss, 1),
        average_grade=round(average_grade, 2) if average_grade is not None else None,
        max_grade=round(max_grade, 2) if max_grade is not None else None,
        min_grade=round(min_grade, 2) if min_grade is not None else None,
        data_source=data_source,
        calculated_at=_now_iso(),
    )


def surface_by_edge_id(graph: RoadGraph, surface_by_way_id: dict[int, str | None]) -> dict[str, str | None]:
    """RoadGraphの各Edgeに、同じOSM取得結果由来のsurfaceタグ（osm_way_id単位）を紐付ける。

    1つのOSM Wayが複数のDirected Edgeに分割されている場合（仕様書9章）、
    それらは同じsurfaceタグ値を共有する（Way単位のタグのため、Way内で路面が変わっても
    OSM上は区別されない。より細かい粒度が必要になった場合は将来の課題とする）。
    """
    return {
        edge_id: surface_by_way_id.get(edge.osm_way_id) if edge.osm_way_id is not None else None
        for edge_id, edge in graph.edges.items()
    }
