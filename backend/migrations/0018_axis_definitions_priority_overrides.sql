-- 改善計画T292。ADR: docs/decisions/t221-axis-registry.md。
--
-- axis_definitionsテーブルへ0次条件（priority_overrides）を追加する。domain/axis_definitions.py:
-- AxisDefinitionへ同じフィールドを追加済み（既定は空リスト=無し、既存軸の挙動には影響しない）。
--
-- レビュー指摘の修正: このカラムを追加するmigrationがT292実装時に漏れており、
-- infrastructure/axis_definition_repository.py（_row_to_definition/upsert）もこのフィールドを
-- 一切読み書きしていなかった。将来priority_overridesを実際に使う軸をDB経由で作成・保存すると、
-- upsert時に値がエラーもログも無いまま保存されず、ロード時は常に空リスト（既定値）へ静かに
-- すり替わる欠陥だったため、カラム追加とリポジトリ側の読み書き（同一コミット）で解消する。
--
-- 既存行はDEFAULT '[]'でbackfillされる（現行7公開軸+内部軸6つはいずれもpriority_overridesを
-- 使わない設計のため、空リストで挙動が変わらない）。
ALTER TABLE axis_definitions
    ADD COLUMN priority_overrides JSONB NOT NULL DEFAULT '[]'::jsonb;
