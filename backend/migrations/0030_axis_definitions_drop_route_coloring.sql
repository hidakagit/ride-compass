-- 改善計画T549（docs/tasks/T549.md）。
--
-- axis_definitionsテーブルから0023 migrationが追加したsupports_route_coloringカラムを
-- 削除する。従来はこのフラグがtrueの軸だけがルート地図の色分けモード（frontend
-- routeStyleModes.ts）の選択肢として現れる設計だったが、この機構の対象外になる軸は
-- 技術的に存在しないと判明したため、フラグを撤去し全公開軸を無条件で対象にする設計へ
-- 変更した（domain/axis_definitions.py: AxisDefinitionのdocstring参照）。
--
-- CLAUDE.md「コミット時の同期ルール」により、本migrationはテーブル構造（DDL）のみを
-- 変更する。time_scopeカラム（0023で同時追加）はこのタスクの対象外のため変更しない。
ALTER TABLE axis_definitions
    DROP COLUMN IF EXISTS supports_route_coloring;
