-- 改善計画T310（ユーザー指示: 「今ハードコードされているところは、軸スタジオレコードに
-- 対応付けて本番DBに移行してほしい」、2026-08-25）。
-- ADR: docs/decisions/t221-axis-registry.md、docs/improvement-plan.md T310。
--
-- axis_definitionsテーブルへ地図チップ表示要素（icon_id/chip_label/panel_hint/
-- proxy_hint/display_override）を追加する。以前はフロント（SECONDARY_AXIS_ICONS等）・
-- backend（axis_display.py: STOP_DENSITY_DISPLAY等）にそれぞれ軸id→値のハードコード
-- 辞書として存在し、軸スタジオ（DB）経由で編集・参照する経路が無かった（既存軸だけの
-- 特別扱い）。domain/axis_definitions.py: AxisDefinitionへ同じフィールドを追加済み
-- （改善計画T310）だが、このDBカラムへの配線が無いと、DB往復（起動時
-- refresh_axis_definitions・管理API書き込み直後の反映）のたびに黙って失われる
-- （0018 migrationのpriority_overrides追加時と同じ欠陥パターン、先回りして対処）。
--
-- 全カラムNULL許容（既定値なし）: 未設定は「フロント側の汎用フォールバックを使う」
-- という意味を持つため、priority_overridesの`[]`既定のような「空だが確定した値」とは
-- 性質が異なる。既存13行（公開7軸＋car_stress内部軸6つ）へのALTER TABLE ADD COLUMN
-- 自体は全カラムNULLのままでも現在の評価結果・地図表示に影響しない（0014〜0018と
-- 同じ「既存の挙動が変わらないことが移行の前提」原則）。
--
-- 続くUPDATE文は、domain/axis_definitions.py: AXIS_DEFINITIONSに手書きしたPython側の
-- 既定値を、対応する軸スタジオレコード（本番DB行）へ同じ内容でbackfillする
-- （ユーザー指示により、Pythonフォールバックだけでなく実際のDB行データとしても
-- 同期させる）。値はaxis_definitions.pyから`model_dump(mode="json")`で機械的に
-- 生成したもの（本migration作成時点、手で書き写していないため転記ミスが無い）。
ALTER TABLE axis_definitions
    ADD COLUMN IF NOT EXISTS icon_id VARCHAR,
    ADD COLUMN IF NOT EXISTS chip_label VARCHAR,
    ADD COLUMN IF NOT EXISTS panel_hint VARCHAR,
    ADD COLUMN IF NOT EXISTS proxy_hint VARCHAR,
    ADD COLUMN IF NOT EXISTS display_override JSONB;

UPDATE axis_definitions
    SET icon_id = 'incline',
        chip_label = '勾配',
        proxy_hint = '（地図表示なし）標高レイヤーで確認できます'
    WHERE axis_id = 'gradient';

UPDATE axis_definitions
    SET icon_id = 'wave',
        chip_label = '舗装'
    WHERE axis_id = 'surface_q';

UPDATE axis_definitions
    SET icon_id = 'crescent-moon',
        chip_label = '夜間'
    WHERE axis_id = 'night';

UPDATE axis_definitions
    SET icon_id = 'density-stack',
        chip_label = '停止密度',
        panel_hint = '信号・横断歩道・一時停止・踏切等の停止要因が、沿線でどれだけ密集しているかの目安です。実際の位置は「停止要因」レイヤーで確認できます。',
        display_override = '{"kind": "ramp", "label": "停止密度", "category": "trafficSafety", "tile_inputs": [{"property": "stop_per_km", "weight": 1.0, "boolean": false, "invert": false, "true_value": 0.0, "false_value": 0.0, "has_unknown_fallback": false, "categories": null, "breakpoints": null}, {"property": "intersection_per_km", "weight": 0.3, "boolean": false, "invert": false, "true_value": 0.0, "false_value": 0.0, "has_unknown_fallback": false, "categories": null, "breakpoints": null}], "thresholds": [1.0, 2.0, 4.0], "unit": "回/km", "note": "信号・横断歩道・一時停止・踏切に無タグ交差点（重み0.3）を加えた停止要因の密度。way単位の事前集計（way_attribute_counts）由来"}'::jsonb
    WHERE axis_id = 'stop_density';

UPDATE axis_definitions
    SET icon_id = 'warning-triangle',
        chip_label = '圧迫感',
        panel_hint = '道路種別・自転車インフラ・制限速度・車線数・指定路線・自動車通行可否から推定した車の圧迫感の目安です。実際の交通量そのものは加味していません。内訳は区間をクリックして確認できます。',
        display_override = '{"kind": "ramp", "label": "車の圧迫感", "category": "trafficSafety", "tile_inputs": [{"property": "highway", "weight": 1.0, "boolean": false, "invert": false, "true_value": 0.0, "false_value": 0.0, "has_unknown_fallback": true, "categories": {"cycleway": 1.0, "living_street": 1.0, "residential": 2.0, "unclassified": 2.0, "track": 2.0, "tertiary": 3.0, "tertiary_link": 3.0, "secondary": 3.0, "secondary_link": 3.0, "primary": 4.0, "primary_link": 4.0, "trunk": 4.0, "trunk_link": 4.0}, "breakpoints": null}, {"property": "bicycle_infra", "weight": 1.0, "boolean": false, "invert": false, "true_value": 0.0, "false_value": 0.0, "has_unknown_fallback": false, "categories": {"separated": -2.0, "lane": -1.0, "shared_busway": 0.0, "shared_pedestrian": 0.0, "roadway": 1.0}, "breakpoints": null}, {"property": "maxspeed_kmh", "weight": 1.0, "boolean": false, "invert": false, "true_value": 0.0, "false_value": 0.0, "has_unknown_fallback": false, "categories": null, "breakpoints": [[0.0, -1.0], [30.0, -1.0], [31.0, 0.0], [59.0, 0.0], [60.0, 1.0], [999.0, 1.0]]}, {"property": "lanes_count", "weight": 1.0, "boolean": false, "invert": false, "true_value": 0.0, "false_value": 0.0, "has_unknown_fallback": false, "categories": null, "breakpoints": [[0.0, -1.0], [1.0, -1.0], [2.0, 0.0], [3.0, 0.0], [4.0, 1.0], [99.0, 1.0]]}, {"property": "designation", "weight": 1.0, "boolean": false, "invert": false, "true_value": 0.0, "false_value": 0.0, "has_unknown_fallback": false, "categories": {"emergency_transport": 1.0, "critical_logistics": 1.0, "both": 1.0}, "breakpoints": null}, {"property": "motor_vehicle_no", "weight": 1.0, "boolean": true, "invert": false, "true_value": -1000.0, "false_value": 0.0, "has_unknown_fallback": false, "categories": null, "breakpoints": null}], "thresholds": [2.0, 3.0, 4.0], "unit": "", "note": "改善計画T292: highway/bicycle_infra/maxspeed_kmh/lanes_count/designation/motor_vehicle_noの6材料から自動計算する。以前は専用の手書きexpression（旧carStressExpression.ts）が必要だったが、内部軸への階層再構成でtile_inputsの重み付き結合として表現できるようになった"}'::jsonb
    WHERE axis_id = 'car_stress';

UPDATE axis_definitions
    SET icon_id = 'density-scatter',
        chip_label = '事故密度',
        panel_hint = '警察庁の交通事故統計をもとに、自転車関連事故が沿線でどれだけ近くに集中しているかの目安です[死亡事故は重めに算入]。実際の発生地点は「事故」レイヤーで確認できます。',
        display_override = '{"kind": "ramp", "label": "事故密度", "category": "trafficSafety", "tile_inputs": [{"property": "accident_per_km", "weight": 1.0, "boolean": false, "invert": false, "true_value": 0.0, "false_value": 0.0, "has_unknown_fallback": false, "categories": null, "breakpoints": null}], "thresholds": [0.4, 0.8, 1.5], "unit": "件/km", "note": "警察庁統計（収録全年分、死亡事故は重み付き）の自転車関連事故の距離正規化密度。way単位の事前集計（way_attribute_counts）由来。正確な事故地点は既存の事故レイヤー（accidents、生の点表示）で確認できる"}'::jsonb
    WHERE axis_id = 'accident';

