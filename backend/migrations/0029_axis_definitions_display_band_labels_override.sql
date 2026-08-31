-- 改善計画T513（docs/tasks/T513.md）。
--
-- axis_definitionsテーブルへ、display_thresholds_overrideと対になる段階ごとの体感
-- ラベルの軽量な上書き（display_band_labels_override）を追加する。domain/
-- axis_definitions.py: AxisDefinition.display_band_labels_overrideへ同じフィールドを
-- 追加済み。
--
-- NULL許容（既定値なし）: 未設定は「数値レンジ表記のみの凡例を使う」という意味を持つ
-- ため、既存行へのALTER TABLE ADD COLUMN自体は全行NULLのままでも現在の地図表示に
-- 影響しない（0025 migrationのdisplay_thresholds_override追加時と同じ「既存の挙動が
-- 変わらないことが移行の前提」原則）。
--
-- CLAUDE.md「コミット時の同期ルール」により、axis_definitionsの行データ（風軸への
-- display_band_labels_override設定）はこのmigrationではなくaxis_admin API（T501の
-- 表示専用フィールド直接編集）経由で行う。本migrationはテーブル構造（DDL）のみを
-- 追加する。
ALTER TABLE axis_definitions
    ADD COLUMN IF NOT EXISTS display_band_labels_override JSONB;
