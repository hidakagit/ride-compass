-- 改善計画T221 Stage D（評価軸のフルレジストリ駆動化＋GUI編集基盤、DBテーブル化）。
-- ADR: docs/decisions/t221-axis-registry.md。
--
-- domain/axis_definitions.pyのAXIS_DEFINITIONS（Stage B/Cで確立した「軸定義データ」の
-- 唯一のソース）をDBテーブルへ昇格させる。migration未適用・接続不可の環境では
-- services/axis_registry_service.pyがWARNINGログを出しつつdomain/axis_definitions.py内蔵の
-- 既定値へ安全側フォールバックするため、本migrationを本番へ適用するまでの間は評価の
-- 振る舞いは一切変わらない（本番migration適用の緊急度が低い設計、docs/improvement-plan.md
-- T74「本番DBが置き去りになる」の教訓を踏まえた意図的な安全側ロールアウト）。
--
-- shape_paramsはdomain/axis_definitions.pyのAxisShape（Pydantic Union）を
-- `model_dump(mode="json")`した内容そのもの（"kind"フィールドで種別を判別、
-- infrastructure/axis_definition_repository.py参照）。sort_orderは合成（composite）の
-- 加算順として意味を持つ（AXIS_DEFINITIONSの辞書挿入順と同じ、Neumaier加算のビット一致
-- 条件のため。tests/test_evaluation_bulk.py参照）。
CREATE TABLE IF NOT EXISTS axis_definitions (
    axis_id TEXT PRIMARY KEY,
    sort_order INTEGER NOT NULL,
    shape_params JSONB NOT NULL,
    default_weight DOUBLE PRECISION NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 軸レジストリ全体の版数（1行のみ）。管理API（axis_admin.py）の書き込みごとに
-- インクリメントする。現時点ではプロセス内キャッシュの無効化には使わない
-- （起動時＋管理API書き込み直後のpush型更新のみのため、同一プロセスではポーリング不要。
-- ADR「Stage D設計メモ」参照）が、将来のマルチプロセス対応・監査用に記録しておく。
CREATE TABLE IF NOT EXISTS axis_registry_meta (
    id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    revision INTEGER NOT NULL DEFAULT 1
);

INSERT INTO axis_registry_meta (id, revision) VALUES (1, 1) ON CONFLICT (id) DO NOTHING;

-- 既存7軸をdomain/axis_definitions.pyのAXIS_DEFINITIONSからそのまま複製した初期データ
-- （挙動が変わらないことがStage移行の前提、T239/Part2と同じ原則）。
INSERT INTO axis_definitions (axis_id, sort_order, shape_params, default_weight) VALUES
('gradient', 0, '{"kind": "breakpoint_linear", "terms": [{"material": "gradient_percent", "weight": 1.0, "required": true}], "preprocess": "abs", "breakpoints": [[0.0, 0.0], [3.0, 25.0], [6.0, 50.0], [9.0, 75.0], [15.0, 100.0]]}', 0.15),
('wind', 1, '{"kind": "breakpoint_linear", "terms": [{"material": "wind_penalty", "weight": 1.0, "required": true}], "preprocess": "identity", "breakpoints": [[0.0, 0.0], [8.0, 100.0]]}', 0.26),
('surface_q', 2, '{"kind": "categorical", "material": "surface_good", "mapping": {"true": 0.0, "false": 80.0}}', 0.19),
('stop_density', 3, '{"kind": "breakpoint_linear", "terms": [{"material": "stop_count_per_km", "weight": 1.0, "required": true}, {"material": "intersection_count_per_km", "weight": 0.3, "required": false}], "preprocess": "identity", "breakpoints": [[0.0, 0.0], [4.0, 100.0]]}', 0.20),
('car_stress', 4, '{"kind": "recipe_then_breakpoint_linear", "terms": [{"material": "car_stress_level", "weight": 1.0, "required": true}], "preprocess": "identity", "breakpoints": [[1.0, 0.0], [5.0, 100.0]]}', 0.20),
('accident', 5, '{"kind": "breakpoint_linear", "terms": [{"material": "accident_count_per_km_year", "weight": 1.0, "required": true}], "preprocess": "identity", "breakpoints": [[0.0, 0.0], [0.5, 100.0]]}', 0.08),
('night', 6, '{"kind": "flag_sum", "flags": [["no_lit", 50.0], ["has_tunnel", 50.0]], "cap": 100.0}', 0.0);
