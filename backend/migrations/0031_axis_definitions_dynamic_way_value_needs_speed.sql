-- 軸スタジオの評価軸定義へ「dedicated_way_value_layer=trueの軸のGET /api/region/
-- dynamic-way-values/{material_id}/...がspeed_kmhクエリパラメータを必須とするか」の
-- 宣言的フィールド（dynamic_way_value_needs_speed）を追加する。0028の
-- dynamic_way_value_needs_time/needs_bearingと同型（domain/axis_definitions.py:
-- AxisDefinition.dynamic_way_value_needs_speed参照）。
--
-- NOT NULL DEFAULT false。既存行の実際の値（風軸が走行速度依存の材料wind_drag_ratioへ
-- 切り替わった時点でtrue）はこのmigrationではなくaxis_admin API経由で設定する
-- （テーブル構造のみを管理する方針、CLAUDE.md「コミット時の同期ルール」）。
ALTER TABLE axis_definitions
    ADD COLUMN IF NOT EXISTS dynamic_way_value_needs_speed BOOLEAN NOT NULL DEFAULT false;
