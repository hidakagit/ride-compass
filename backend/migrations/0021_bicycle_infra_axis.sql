-- 改善計画T347（ユーザー指示: 「同等の軸を登録し、bicycle_infraを削除したい」
-- 「フォールバックも不要」「classify_bicycle_infrastructureの存在自体がPython側に
-- 生データ加工ロジックを持たせない設計原則に反する」、2026-08-26）。
--
-- material_catalog.pyのbicycle_infra材料（優先順位付き分類）・domain/traffic.py:
-- classify_bicycle_infrastructure・MVTタイルのbicycle_infraプロパティを削除し、
-- 既に評価に使われている正規化フラグ材料4種（highway_is_cycleway/cycleway_has_track/
-- cycleway_has_lane/cycleway_has_shared、domain/recipe.py: bicycle_infra_flags）だけを
-- 正準とする。本migrationは対応するDB側の変更3点をまとめる。
--
-- (1) car_stress_bicycle_infra_adjustment内部軸のshape_paramsドリフト修正。
--     改善計画T336でコード側（axis_definitions.py）は categorical(material="bicycle_infra")
--     から breakpoint_linear（正規化フラグ4種の重み付き線形和、実データ検証済み
--     0.0127%ズレ）へ既に切り替わっていたが、対応するmigrationが一度も書かれておらず
--     0017 migrationのshape_paramsが旧categorical形のまま残っていた（T347着手時に発覚。
--     本タスク以前から存在した潜在バグ）。bicycle_infra材料をこのmigrationで削除する
--     ため、ここで放置すると本migration適用環境で「存在しない材料を参照する」壊れた
--     shape_paramsになる。値はdomain/axis_definitions.py:
--     AXIS_DEFINITIONS["car_stress_bicycle_infra_adjustment"].shape.model_dump(mode="json")
--     の出力と1:1で一致させてある（0014〜0020と同じ「DBの内容とコード内蔵の既定値を
--     一致させる」原則）。
UPDATE axis_definitions SET shape_params =
 '{"kind": "breakpoint_linear", "terms": [{"material": "highway_is_cycleway", "weight": -4.0, "required": true}, {"material": "cycleway_has_track", "weight": -4.0, "required": true}, {"material": "cycleway_has_lane", "weight": -2.0, "required": true}, {"material": "cycleway_has_shared", "weight": -1.0, "required": true}], "preprocess": "identity", "breakpoints": [[-11.0, -2.0], [-4.0, -2.0], [-3.0, -1.0], [-2.0, -1.0], [-1.0, 0.0], [0.0, 1.0]]}'
 WHERE axis_id = 'car_stress_bicycle_infra_adjustment';

-- (2) 新設の公開軸「自転車インフラ」（bicycle_infra_quality）を追加する。
--     正規化フラグ4種を直接持たず、car_stress_bicycle_infra_adjustment（同じ4フラグの
--     重み付き線形和、実データ検証済み）を単一の材料（軸参照）として受け取り、
--     breakpointsだけをdifficultyの規約（0=最も走りやすい・100=最も走りにくい）へ
--     線形再スケールする（ユーザー指摘: 生の4材料を2軸が別々に持つと
--     check_material_exclusivity[材料の排他帰属チェック]が二重計上として拒否するため、
--     car_stress自身が内部軸を合成するのと同じ階層構造[改善計画T292]へ作り替えた）。
--     sort_orderは既存0-12（公開7軸+car_stress内部軸6つ）の次の13
--     （axis_registry_service.create()のsort_order算出と同じ「既存最大+1」原則）。
--     地図表示は持たない（show_map_icon=false。旧bicycle_infraタイルプロパティ自体を
--     削除したため、この4フラグから地図ramp用のタイル値を新設しない限り地図表示
--     できず、今回はスコープ外）。値はdomain/axis_definitions.py:
--     AXIS_DEFINITIONS["bicycle_infra_quality"]と1:1で一致させてある。
INSERT INTO axis_definitions
    (axis_id, sort_order, shape_params, default_weight, label, description, category, is_published, chip_label, show_map_icon) VALUES
('bicycle_infra_quality', 13,
 '{"kind": "breakpoint_linear", "terms": [{"material": "car_stress_bicycle_infra_adjustment", "weight": 1.0, "required": true}], "preprocess": "identity", "breakpoints": [[-2.0, 0.0], [-1.0, 33.3], [0.0, 66.7], [1.0, 100.0]]}',
 0.15, '自転車インフラ', '専用の自転車インフラ（分離自転車道・自転車レーン等）が整備されているほど易しい。', '推定', true,
 '自転車道', false);

-- (3) car_stress軸のdisplay_override（地図ランプ表示宣言）から、削除するbicycle_infra
--     タイルプロパティを参照するtile_inputを取り除き、note文言を6材料→5材料へ更新する
--     （Python側のdomain/axis_definitions.py: AXIS_DEFINITIONS["car_stress"]は既に
--     この内容へ更新済み。評価側のcar_stress自身のterms
--     [car_stress_bicycle_infra_adjustment内部軸]には影響しない、地図ランプ表示専用の
--     tile_inputsのみの変更）。
UPDATE axis_definitions
    SET display_override = '{"kind": "ramp", "label": "車の圧迫感", "category": "trafficSafety", "tile_inputs": [{"property": "highway", "weight": 1.0, "boolean": false, "invert": false, "true_value": 0.0, "false_value": 0.0, "has_unknown_fallback": true, "categories": {"cycleway": 1.0, "living_street": 1.0, "primary": 4.0, "primary_link": 4.0, "residential": 2.0, "secondary": 3.0, "secondary_link": 3.0, "tertiary": 3.0, "tertiary_link": 3.0, "track": 2.0, "trunk": 4.0, "trunk_link": 4.0, "unclassified": 2.0}, "breakpoints": null}, {"property": "maxspeed_kmh", "weight": 1.0, "boolean": false, "invert": false, "true_value": 0.0, "false_value": 0.0, "has_unknown_fallback": false, "categories": null, "breakpoints": [[0.0, -1.0], [30.0, -1.0], [31.0, 0.0], [59.0, 0.0], [60.0, 1.0], [999.0, 1.0]]}, {"property": "lanes_count", "weight": 1.0, "boolean": false, "invert": false, "true_value": 0.0, "false_value": 0.0, "has_unknown_fallback": false, "categories": null, "breakpoints": [[0.0, -1.0], [1.0, -1.0], [2.0, 0.0], [3.0, 0.0], [4.0, 1.0], [99.0, 1.0]]}, {"property": "designation", "weight": 1.0, "boolean": false, "invert": false, "true_value": 0.0, "false_value": 0.0, "has_unknown_fallback": false, "categories": {"both": 1.0, "critical_logistics": 1.0, "emergency_transport": 1.0}, "breakpoints": null}, {"property": "motor_vehicle_no", "weight": 1.0, "boolean": true, "invert": false, "true_value": -1000.0, "false_value": 0.0, "has_unknown_fallback": false, "categories": null, "breakpoints": null}], "thresholds": [2.0, 3.0, 4.0], "unit": "", "note": "改善計画T292: highway/maxspeed_kmh/lanes_count/designation/motor_vehicle_noの5材料から自動計算する。以前は専用の手書きexpression（旧carStressExpression.ts）が必要だったが、内部軸への階層再構成でtile_inputsの重み付き結合として表現できるようになった（改善計画T347でbicycle_infraタイルプロパティ自体を削除したため6→5材料へ）"}'::jsonb
    WHERE axis_id = 'car_stress';
