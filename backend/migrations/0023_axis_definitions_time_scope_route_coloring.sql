-- 改善計画T352（axis_idハードコード分岐を宣言的フィールドへ汎用化）。
--
-- axis_definitionsテーブルへ2つの宣言的フィールドを追加する。
--
-- 1. time_scope（TEXT、既定'always'）: この軸の重みが常に有効か、特定の時間帯
--    （現状は'night_only'のみ）でのみ有効かの宣言。従来road_graph_engine.py/
--    openrouteservice_engine.pyがaxis_id"night"を直接ハードコード分岐していた
--    T173ロジックを、この性質ベースのフィールドへ置き換える
--    （domain/axis_definitions.py: AxisDefinition.time_scope・time_scoped_weights参照）。
--    既存全軸は'always'が正しい既定値のため、night軸のみ明示的に'night_only'へ
--    backfillする。
--
-- 2. supports_route_coloring（BOOLEAN、既定false）: この軸のdifficultyを、
--    ルート地図の色分けモード（frontend routeStyleModes.ts）の選択肢として動的に
--    使えるかの宣言。従来RouteStyleModeIdが"wind"を直接ハードコードしていたのを
--    置き換える。wind軸のみtrueへbackfillする（gradientは対象外のまま——生材料
--    gradient_percentを直接読む特殊実装のため、domain/axis_definitions.py:
--    AxisDefinition.supports_route_coloringのdocstring参照）。
ALTER TABLE axis_definitions
    ADD COLUMN IF NOT EXISTS time_scope TEXT NOT NULL DEFAULT 'always',
    ADD COLUMN IF NOT EXISTS supports_route_coloring BOOLEAN NOT NULL DEFAULT false;

UPDATE axis_definitions SET time_scope = 'night_only' WHERE axis_id = 'night';
UPDATE axis_definitions SET supports_route_coloring = true WHERE axis_id = 'wind';
