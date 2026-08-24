-- 改善計画T292（car_stress軸を内部軸5つ＋公開軸1つの階層構造で再定義）。
-- ADR: docs/decisions/t221-axis-registry.md。
--
-- 専用Pythonレシピ（旧CarStressRecipe/RoadSuitabilityRecipe/MotorVehicleDensityRecipe/
-- car_closeness/road_suitability/cycleway_adjustment/car_stress_level等、domain/recipe.py・
-- domain/traffic.pyから削除済み）を廃止し、highway基準値＋4つの補正＋motor_vehicle=no
-- 優先確定の計6内部軸（is_published=false、他の公開軸から参照される専用の推定軸）を
-- 新規追加し、既存car_stress行のshape_paramsをこれら6内部軸を参照する階層構造へ
-- 更新する。値はすべてdomain/axis_definitions.py: AXIS_DEFINITIONSのPythonコード内蔵値
-- （`AxisShape.model_dump(mode="json")`の出力）と1:1で一致させてある（0014/0015/0016と
-- 同じ「DBの内容とコード内蔵の既定値を一致させる」原則）。
--
-- 未適用の環境ではservices/axis_registry_service.pyが従来どおりWARNINGログを出しつつ
-- domain/axis_definitions.py内蔵の新既定値（内部軸6つ込み）へ安全側フォールバックする
-- ため、本migrationを本番へ適用するまでの間はコード側の新しい評価ロジックがそのまま
-- 使われる（0014〜0016と異なり、今回はコード側が既に新ロジックへ切り替わっている点に
-- 注意——本migration未適用でも挙動はコード内蔵値どおりで変わらない。ただし軸スタジオ
-- 経由でcar_stressやその内部軸を編集したい場合はDB適用が前提となる）。
--
-- sort_orderは既存7軸（0-6）の後ろへ内部軸6つを追加する（7-12）。内部軸はis_published=false
-- のため一般向けAPI（GET /api/axis-catalog）・3次合成の重み付け対象には含まれず、
-- sort_order自体が評価結果へ影響することはない（domain/axis_definitions.py:
-- topological_axis_orderが依存順で並べ替えるため）。

-- 内部軸6つを新規追加。
INSERT INTO axis_definitions (axis_id, sort_order, shape_params, default_weight, label, description, category, is_published) VALUES
('car_stress_highway_base', 7,
 '{"kind": "categorical", "material": "highway", "mapping": {"cycleway": 1.0, "living_street": 1.0, "residential": 2.0, "unclassified": 2.0, "track": 2.0, "tertiary": 3.0, "tertiary_link": 3.0, "secondary": 3.0, "secondary_link": 3.0, "primary": 4.0, "primary_link": 4.0, "trunk": 4.0, "trunk_link": 4.0}}',
 0.0, '車ストレス内部軸: highway基準値', 'highway種別による車の圧迫感の基準値(1-4、非公開)', '推定', false),
('car_stress_bicycle_infra_adjustment', 8,
 '{"kind": "categorical", "material": "bicycle_infra", "mapping": {"separated": -2.0, "lane": -1.0, "shared_busway": 0.0, "shared_pedestrian": 0.0, "roadway": 1.0}}',
 0.0, '車ストレス内部軸: 自転車インフラ補正', '自転車インフラ種別による補正(非公開)', '推定', false),
('car_stress_maxspeed_adjustment', 9,
 '{"kind": "breakpoint_linear", "terms": [{"material": "maxspeed_kmh", "weight": 1.0, "required": true}], "preprocess": "identity", "breakpoints": [[0.0, -1.0], [30.0, -1.0], [31.0, 0.0], [59.0, 0.0], [60.0, 1.0], [999.0, 1.0]]}',
 0.0, '車ストレス内部軸: 制限速度補正', '制限速度による補正(非公開)', '推定', false),
('car_stress_lanes_adjustment', 10,
 '{"kind": "breakpoint_linear", "terms": [{"material": "lanes_count", "weight": 1.0, "required": true}], "preprocess": "identity", "breakpoints": [[0.0, -1.0], [1.0, -1.0], [2.0, 0.0], [3.0, 0.0], [4.0, 1.0], [99.0, 1.0]]}',
 0.0, '車ストレス内部軸: 車線数補正', '車線数による補正(非公開)', '推定', false),
('car_stress_designation_adjustment', 11,
 '{"kind": "categorical", "material": "is_designated", "mapping": {"true": 1.0, "false": 0.0}}',
 0.0, '車ストレス内部軸: 指定路線補正', '指定路線(緊急輸送道路・重要物流道路)該当による補正(非公開)', '推定', false),
('car_stress_motor_vehicle_no_adjustment', 12,
 '{"kind": "categorical", "material": "motor_vehicle_no", "mapping": {"true": -1000.0, "false": 0.0}}',
 0.0, '車ストレス内部軸: 自動車通行不可の優先確定', 'motor_vehicle=noの区間を最良値へ強制する内部軸(非公開)', '推定', false);

-- 既存car_stress行を内部軸6つを参照する階層構造のshape_paramsへ更新する
-- （label/description/category/default_weight/is_published/sort_orderは変更なし）。
UPDATE axis_definitions SET shape_params =
 '{"kind": "breakpoint_linear", "terms": [{"material": "car_stress_highway_base", "weight": 1.0, "required": true}, {"material": "car_stress_bicycle_infra_adjustment", "weight": 1.0, "required": false}, {"material": "car_stress_maxspeed_adjustment", "weight": 1.0, "required": false}, {"material": "car_stress_lanes_adjustment", "weight": 1.0, "required": false}, {"material": "car_stress_designation_adjustment", "weight": 1.0, "required": false}, {"material": "car_stress_motor_vehicle_no_adjustment", "weight": 1.0, "required": false}], "preprocess": "identity", "breakpoints": [[1.0, 0.0], [5.0, 100.0]]}'
 WHERE axis_id = 'car_stress';
