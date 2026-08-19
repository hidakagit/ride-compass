from app.domain.evaluation import RoutePreference
from app.domain.recipe import MotorVehicleDensityRecipe, RoadSuitabilityRecipe
from app.domain.recipe_definition import (
    Recipe,
    default_recipe,
    recipe_from_components,
    recipe_to_components,
)
from app.domain.traffic import CarStressRecipe


class TestDefaultRecipe:
    def test_has_recipe_id_and_version(self):
        recipe = default_recipe()
        assert recipe.recipe_id == "default"
        assert recipe.version == 1

    def test_custom_recipe_id_and_version(self):
        recipe = default_recipe("night_ride", 3)
        assert recipe.recipe_id == "night_ride"
        assert recipe.version == 3

    def test_hard_filters_matches_default_hard_filters(self):
        recipe = default_recipe()
        assert set(recipe.hard_filters) == {"no_bicycle", "motorway", "trunk"}

    def test_round_trips_to_class_default_components(self):
        components = recipe_to_components(default_recipe())
        assert components.preference == RoutePreference()
        assert components.car_stress_recipe == CarStressRecipe()
        assert components.road_suitability_recipe == RoadSuitabilityRecipe()
        assert components.motor_vehicle_density_recipe == MotorVehicleDensityRecipe()
        assert components.hard_filters == frozenset({"no_bicycle", "motorway", "trunk"})


class TestRecipeRoundTrip:
    def test_custom_components_round_trip_preserves_values(self):
        preference = RoutePreference(night_weight=0.3, car_stress_weight=0.1)
        car_stress_recipe = CarStressRecipe(lanes_low_threshold=2, lanes_low_adjustment=-2)
        road_suitability_recipe = RoadSuitabilityRecipe(cycleway_track_adjustment=-3)
        motor_vehicle_density_recipe = MotorVehicleDensityRecipe(maxspeed_high_adjustment=2)

        recipe = recipe_from_components(
            "night_ride",
            2,
            preference,
            car_stress_recipe,
            road_suitability_recipe,
            motor_vehicle_density_recipe,
            hard_filters=frozenset({"motorway"}),
        )
        components = recipe_to_components(recipe)

        assert components.preference == preference
        assert components.car_stress_recipe == car_stress_recipe
        assert components.road_suitability_recipe == road_suitability_recipe
        assert components.motor_vehicle_density_recipe == motor_vehicle_density_recipe
        assert components.hard_filters == frozenset({"motorway"})


class TestArbitraryRecipeJson:
    def test_recipe_built_from_plain_dict_extracts_axis_params_and_weights(self):
        # 設計プロンプトのレシピJSONスキーマ例と同じ形（recipe_id+version付きの生dict）を
        # Recipe化し、軸内係数・重みの両方が一意に取り出せることを確認する（T141完了条件）。
        raw = {
            "recipe_id": "default_day",
            "version": 3,
            "hard_filters": ["no_bicycle", "motorway"],
            "axis_params": {
                "road_suitability": {"cycleway_track_adjustment": -3},
                "car_stress": {"lanes_low_threshold": 2, "lanes_low_adjustment": -2},
            },
            "weights": {
                "elevation_weight": 0.1,
                "road_weight": 0.1,
                "wind_weight": 0.1,
                "stop_weight": 0.1,
                "car_stress_weight": 0.4,
                "accident_weight": 0.1,
                "night_weight": 0.0,
            },
        }

        recipe = Recipe(**raw)
        components = recipe_to_components(recipe)

        assert components.road_suitability_recipe.cycleway_track_adjustment == -3
        assert components.car_stress_recipe.lanes_low_threshold == 2
        assert components.preference.car_stress_weight == 0.4
        assert components.hard_filters == frozenset({"no_bicycle", "motorway"})
        # axis_paramsで省略した軸(motor_vehicle_density)はクラス既定値へフォールバック
        assert components.motor_vehicle_density_recipe == MotorVehicleDensityRecipe()

    def test_recipe_omitting_axis_params_falls_back_to_defaults_for_all_axes(self):
        raw = {
            "recipe_id": "weights_only",
            "version": 1,
            "hard_filters": ["no_bicycle", "motorway", "trunk"],
            "axis_params": {},
            "weights": RoutePreference().model_dump(),
        }

        components = recipe_to_components(Recipe(**raw))

        assert components.car_stress_recipe == CarStressRecipe()
        assert components.road_suitability_recipe == RoadSuitabilityRecipe()
        assert components.motor_vehicle_density_recipe == MotorVehicleDensityRecipe()
