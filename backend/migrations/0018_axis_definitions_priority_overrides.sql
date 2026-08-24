-- 改善計画T292（コードレビュー指摘の修正）。
-- ADR: docs/decisions/t221-axis-registry.md。
--
-- axis_definitionsテーブルへ0次条件（priority_overrides）を追加する。domain/axis_definitions.py:
-- AxisDefinition.priority_overridesへ同じフィールドを追加済み（改善計画T292）だが、
-- このDBカラム・軸スタジオ管理API（axis_admin.py）双方への配線が漏れており、
-- DB往復（起動時refresh_axis_definitions・管理API書き込み直後の反映）のたびに
-- 設定した0次条件が黙って失われる欠陥がコードレビューで発覚した。
--
-- 既存13行（公開7軸＋car_stress内部軸6つ）はいずれもpriority_overrides=[]のため、
-- NOT NULL DEFAULT '[]'でbackfillしても現在の評価結果に影響しない（0014〜0017と
-- 同じ「既存の挙動が変わらないことが移行の前提」原則）。
--
-- 未適用の環境ではservices/axis_registry_service.pyが従来どおりWARNINGログを出しつつ
-- domain/axis_definitions.py内蔵の既定値へ安全側フォールバックするため、本migrationを
-- 本番へ適用するまでの間は評価の振る舞いは変わらない。
ALTER TABLE axis_definitions
    ADD COLUMN priority_overrides JSONB NOT NULL DEFAULT '[]';
