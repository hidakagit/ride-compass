-- 軸スタジオの評価軸定義へ「dedicated_way_value_layer=trueの軸のGET /api/region/
-- dynamic-way-values/{material_id}/...がat/bearing_degクエリパラメータを必須とするか」の
-- 宣言的フィールド（dynamic_way_value_needs_time/dynamic_way_value_needs_bearing）を
-- 追加する。domain/axis_definitions.py: AxisDefinitionへ同じフィールドを追加済み。
--
-- 従来domain/dynamic_way_values.py: DYNAMIC_WAY_VALUE_MATERIALSが軸スタジオ
-- （dedicated_way_value_layer）とは独立したPython辞書へこの値をハードコードしており、
-- 3件目の動的材料を追加するには軸スタジオでの登録に加えてコード変更・再デプロイが必要
-- だった（改善計画T458）。dedicated_way_value_layerと同様、この値自体は軸の評価ロジック
-- （shape）からは自動導出できない工学的事実のため、明示的なフィールドとして持たせる。
--
-- NOT NULL DEFAULT false（既定値なし＝dedicated_way_value_layer=falseの大多数の軸では
-- 意味を持たないフィールドのため、既存行へのALTER TABLE ADD COLUMN自体は全行falseの
-- ままでも現在の挙動に影響しない）。
--
-- CLAUDE.md「コミット時の同期ルール」により、axis_definitionsの行データ（wind/gradientの
-- 実際の値へのbackfill）はこのmigrationではなくaxis_admin API（unpublish→PUT→republish）
-- 経由で行う。本migrationはテーブル構造（DDL）のみを追加する
-- （0027_axis_definitions_dedicated_way_value_layer.sqlと同じ方針）。
ALTER TABLE axis_definitions
    ADD COLUMN IF NOT EXISTS dynamic_way_value_needs_time BOOLEAN NOT NULL DEFAULT false;

ALTER TABLE axis_definitions
    ADD COLUMN IF NOT EXISTS dynamic_way_value_needs_bearing BOOLEAN NOT NULL DEFAULT false;
