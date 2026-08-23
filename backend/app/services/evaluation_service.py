from pathlib import Path

import yaml

from app.domain.attributes import ElevationAttribute
from app.domain.evaluation import (
    EdgeCostResult,
    RoutePreference,
    compute_edge_costs_bulk,
)
from app.domain.graph import RoadGraphLike
from app.domain.recipe import MotorVehicleDensityRecipe, RoadSuitabilityRecipe
from app.domain.traffic import CarStressRecipe
from app.domain.weather import WeatherConditions

ROUTE_PREFERENCE_CONFIG_PATH = Path(__file__).resolve().parent.parent / "route_preference.yaml"
CAR_STRESS_RECIPE_CONFIG_PATH = Path(__file__).resolve().parent.parent / "car_stress_recipe.yaml"
ROAD_SUITABILITY_RECIPE_CONFIG_PATH = Path(__file__).resolve().parent.parent / "road_suitability_recipe.yaml"
MOTOR_VEHICLE_DENSITY_RECIPE_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent / "motor_vehicle_density_recipe.yaml"
)


def _load_yaml_section(path: Path, key: str) -> dict:
    """`path`のYAMLファイルからトップレベルキー`key`の中身を読み込む（load_route_preference等
    3関数の共通部分）。リクエストの都度再読込する（dependencies.py:
    get_route_generation_builder参照。サーバー再起動なしでYAML編集を反映する意図的な挙動のため
    キャッシュしない）。
    """
    with open(path, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return config[key]


def load_route_preference(path: Path = ROUTE_PREFERENCE_CONFIG_PATH) -> RoutePreference:
    """route_preference.yamlから既定のRoute Preference（重み）を読み込む（仕様書27-28章）。

    scoring.yaml/load_scoring_weights（ルート単位のRouteScorer用）と同じパターンだが、
    対象・データ構造が異なる別設定のため、別ファイル・別関数として分離している
    （Phase 4完了時点の引き継ぎ事項を参照）。呼び出し元が`path`を差し替えれば、
    将来複数プロファイル（快適性重視/トレーニング重視等、仕様書27・45章）を
    別ファイルとして追加した場合もコード変更なしで切り替えられる。
    """
    return RoutePreference(weights=_load_yaml_section(path, "route_preference"))


def load_car_stress_recipe(path: Path = CAR_STRESS_RECIPE_CONFIG_PATH) -> CarStressRecipe:
    """car_stress_recipe.yamlから既定の車ストレスレシピ（軸の中身、
    domain/traffic.py: CarStressRecipe参照）を読み込む。load_route_preferenceと同じ
    パターン（軸間の重みとは別階層の設定のため別ファイル・別関数）。
    """
    return CarStressRecipe(**_load_yaml_section(path, "car_stress_recipe"))


def load_road_suitability_recipe(path: Path = ROAD_SUITABILITY_RECIPE_CONFIG_PATH) -> RoadSuitabilityRecipe:
    """road_suitability_recipe.yamlから既定の道路適正レシピ（domain/recipe.py:
    RoadSuitabilityRecipe参照）を読み込む。車ストレス・安全度が共有する「車との近さ」(N2)
    の材料の1つ（改善計画: 車との近さ材料の共有元化）。load_car_stress_recipeと同じ
    パターン。
    """
    return RoadSuitabilityRecipe(**_load_yaml_section(path, "road_suitability_recipe"))


def load_motor_vehicle_density_recipe(
    path: Path = MOTOR_VEHICLE_DENSITY_RECIPE_CONFIG_PATH,
) -> MotorVehicleDensityRecipe:
    """motor_vehicle_density_recipe.yamlから既定の自動車密度レシピ（domain/recipe.py:
    MotorVehicleDensityRecipe参照）を読み込む。load_road_suitability_recipeと同じ役割
    （改善計画: 車との近さ材料の共有元化）。
    """
    return MotorVehicleDensityRecipe(**_load_yaml_section(path, "motor_vehicle_density_recipe"))


class EvaluationService:
    """Evaluation Engineのオーケストレーション層（仕様書26章）。

    I/Oは行わない。属性の取得自体はPhase 3の`ElevationAttributeService`・
    `GraphService.get_or_build_graph_with_attributes`が担当し、ここでは
    既に取得済みのRoadGraph・属性からEdge Costを算出するのみ。Route Engineからは
    独立しており、既存のルート探索（RoutingService/RouteGenerator）からは参照されない。
    """

    def __init__(
        self,
        preference: RoutePreference | None = None,
        car_stress_recipe: CarStressRecipe | None = None,
        road_suitability_recipe: RoadSuitabilityRecipe | None = None,
        motor_vehicle_density_recipe: MotorVehicleDensityRecipe | None = None,
    ):
        self._preference = preference or load_route_preference()
        self._car_stress_recipe = car_stress_recipe or load_car_stress_recipe()
        self._road_suitability_recipe = road_suitability_recipe or load_road_suitability_recipe()
        self._motor_vehicle_density_recipe = motor_vehicle_density_recipe or load_motor_vehicle_density_recipe()

    def evaluate_graph(
        self,
        graph: RoadGraphLike,
        elevation_attributes: dict[str, ElevationAttribute],
        surface_attributes: dict[str, str | None],
        wind: WeatherConditions | None = None,
        stop_counts: dict[str, int] | None = None,
        way_tags: dict[str, dict[str, str]] | None = None,
        intersection_counts: dict[str, int] | None = None,
        accident_counts: dict[str, int] | None = None,
        accident_years_covered: int = 0,
        designated_edge_ids: set[str] | None = None,
        preference: RoutePreference | None = None,
        penalty_strength: float = 1.0,
        max_average_grade_percent: float | None = None,
    ) -> dict[str, EdgeCostResult]:
        # preference省略時はself._preference（コンストラクタ注入・全リクエスト共有）を使う。
        # 改善計画T173: RoadGraphEngineが出発時刻に応じてnight_weightだけを差し替えた
        # RoutePreferenceを渡せるよう、呼び出し側でオーバーライドできる引数として追加した
        # （self._preferenceを直接書き換えるとリクエスト間で共有される状態を汚染するため、
        # 呼び出し元がmodel_copyしたコピーをこちらへ渡す設計）。
        # penalty_strength（改善計画T218・T12 ADR原則1）はコスト式の割増率の強さを
        # 調整するリクエストパラメータ（既定1.0）。domain/evaluation.py:
        # compute_cost_from_axis_scores参照。
        # max_average_grade_percent（改善計画T218a・T12 ADR原則5）は0次ハードフィルタの
        # 勾配しきい値（既定None＝除外しない）。domain/evaluation.py: is_edge_allowed参照。
        preference = preference or self._preference
        stop_counts = stop_counts or {}
        designated_edge_ids = designated_edge_ids or set()
        # 改善計画T221 Stage B: RoutePreference自体がaxis_idキーの重み辞書を持つため
        # そのまま渡す（T220で導入した「graph全体で1回だけ重みを解決する」意図は不変）。
        weights = preference.weights
        # 改善計画T240: compute_edge_costを1件ずつ呼ぶPythonループから、numpyベクトル化した
        # compute_edge_costs_bulkへ切り替えた（Edge数万〜十数万件規模での実行時間短縮）。
        # スカラー版compute_edge_costは削除せず、tests/test_evaluation_bulk.pyの回帰
        # オラクルとして存続させている。
        return compute_edge_costs_bulk(
            graph,
            elevation_attributes,
            surface_attributes,
            preference,
            car_stress_recipe=self._car_stress_recipe,
            road_suitability_recipe=self._road_suitability_recipe,
            motor_vehicle_density_recipe=self._motor_vehicle_density_recipe,
            wind=wind,
            stop_counts=stop_counts,
            way_tags=way_tags,
            intersection_counts=intersection_counts,
            accident_counts=accident_counts,
            accident_years_covered=accident_years_covered,
            designated_edge_ids=designated_edge_ids,
            penalty_strength=penalty_strength,
            max_average_grade_percent=max_average_grade_percent,
            weights=weights,
        )
