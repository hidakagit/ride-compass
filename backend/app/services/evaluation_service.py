from pathlib import Path

import yaml

from app.domain.attributes import ElevationAttribute
from app.domain.evaluation import EdgeCostResult, RoutePreference, compute_edge_cost
from app.domain.graph import RoadGraph
from app.domain.traffic import TrafficStressRecipe
from app.domain.weather import WeatherConditions

ROUTE_PREFERENCE_CONFIG_PATH = Path(__file__).resolve().parent.parent / "route_preference.yaml"
TRAFFIC_STRESS_RECIPE_CONFIG_PATH = Path(__file__).resolve().parent.parent / "traffic_stress_recipe.yaml"


def load_route_preference(path: Path = ROUTE_PREFERENCE_CONFIG_PATH) -> RoutePreference:
    """route_preference.yamlから既定のRoute Preference（重み）を読み込む（仕様書27-28章）。

    scoring.yaml/load_scoring_weights（ルート単位のRouteScorer用）と同じパターンだが、
    対象・データ構造が異なる別設定のため、別ファイル・別関数として分離している
    （Phase 4完了時点の引き継ぎ事項を参照）。呼び出し元が`path`を差し替えれば、
    将来複数プロファイル（快適性重視/トレーニング重視等、仕様書27・45章）を
    別ファイルとして追加した場合もコード変更なしで切り替えられる。
    """
    with open(path, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return RoutePreference(**config["route_preference"])


def load_traffic_stress_recipe(path: Path = TRAFFIC_STRESS_RECIPE_CONFIG_PATH) -> TrafficStressRecipe:
    """traffic_stress_recipe.yamlから既定の交通ストレスレシピ（軸の中身、
    domain/traffic.py: TrafficStressRecipe参照）を読み込む。load_route_preferenceと同じ
    パターン（軸間の重みとは別階層の設定のため別ファイル・別関数）。
    """
    with open(path, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return TrafficStressRecipe(**config["traffic_stress_recipe"])


class EvaluationService:
    """Evaluation Engineのオーケストレーション層（仕様書26章）。

    I/Oは行わない。属性の取得自体はPhase 3の`ElevationAttributeService`・
    `GraphService.build_graph_with_surface_tags_for_bbox`が担当し、ここでは
    既に取得済みのRoadGraph・属性からEdge Costを算出するのみ。Route Engineからは
    独立しており、既存のルート探索（RoutingService/RouteGenerator）からは参照されない。
    """

    def __init__(
        self,
        preference: RoutePreference | None = None,
        traffic_stress_recipe: TrafficStressRecipe | None = None,
    ):
        self._preference = preference or load_route_preference()
        self._traffic_stress_recipe = traffic_stress_recipe or load_traffic_stress_recipe()

    def evaluate_graph(
        self,
        graph: RoadGraph,
        elevation_attributes: dict[str, ElevationAttribute],
        surface_attributes: dict[str, str | None],
        wind: WeatherConditions | None = None,
        stop_counts: dict[str, int] | None = None,
        way_tags: dict[str, dict[str, str]] | None = None,
        intersection_counts: dict[str, int] | None = None,
        accident_counts: dict[str, int] | None = None,
        accident_years_covered: int = 0,
        designated_edge_ids: set[str] | None = None,
    ) -> dict[str, EdgeCostResult]:
        stop_counts = stop_counts or {}
        designated_edge_ids = designated_edge_ids or set()
        return {
            edge_id: compute_edge_cost(
                edge,
                elevation_attributes.get(edge_id),
                surface_attributes.get(edge_id),
                self._preference,
                wind=wind,
                stop_count=stop_counts.get(edge_id),
                way_tags=way_tags.get(edge_id) if way_tags is not None else None,
                intersection_count=intersection_counts.get(edge_id) if intersection_counts is not None else None,
                accident_count=accident_counts.get(edge_id) if accident_counts is not None else None,
                accident_years_covered=accident_years_covered,
                is_designated=edge_id in designated_edge_ids,
                traffic_stress_recipe=self._traffic_stress_recipe,
            )
            for edge_id, edge in graph.edges.items()
        }
