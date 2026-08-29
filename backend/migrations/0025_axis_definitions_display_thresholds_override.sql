-- 改善計画T404（display_override廃止方針、docs/tasks/T404.md）。
--
-- axis_definitionsテーブルへ地図の色分けしきい値だけを差し替える軽量な上書き
-- （display_thresholds_override）を追加する。domain/axis_definitions.py:
-- AxisDefinition.display_thresholds_overrideへ同じフィールドを追加済み。
--
-- NULL許容（既定値なし）: 未設定は「derive_ramp_inputsが計算したしきい値をそのまま使う」
-- という意味を持つため、既存行へのALTER TABLE ADD COLUMN自体は全行NULLのままでも
-- 現在の評価結果・地図表示に影響しない（0019 migrationのdisplay_override追加時と
-- 同じ「既存の挙動が変わらないことが移行の前提」原則）。
--
-- CLAUDE.md「コミット時の同期ルール」により、axis_definitionsの行データ（既存
-- car_stress/stop_density/accident 3軸のdisplay_thresholds_override設定・
-- display_overrideのNULL化）はこのmigrationではなくaxis_admin API（unpublish→
-- PUT→republish）経由で行う。本migrationはテーブル構造（DDL）のみを追加する。
ALTER TABLE axis_definitions
    ADD COLUMN IF NOT EXISTS display_thresholds_override JSONB;
