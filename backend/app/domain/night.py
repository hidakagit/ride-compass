"""夜間（街灯・トンネル）の材料タグ解決（改善計画T139）。

`lit`タグ不在は「街灯なしとみなす」（unknown safeの原則から外れる意図的な選択。litタグは
明示的に付与されている場合のみ確認できる情報で、多くのwayは単にタグが無いだけだが、
「街灯があるかどうか分からない区間」を「街灯ありと同等に扱う」よりは安全側に倒すほうが
夜間ライドの実用上望ましいと判断した）。既定重み`night`＝0.0（`domain/axis_definitions.py`）
のため、この判断が既定の経路・スコアに影響することはない。

「走りにくさ0-100、大きいほど大変」という向きは、この関数ではなく夜間軸定義自身の
`lit`項の重み（負値）が担う（`domain/axis_definitions.py`のnight軸定義参照）。

改善計画T221 Stage B/C: 加点値・上限（フラグ加算テンプレートのパラメータ）は
`domain/axis_definitions.py`のnight軸定義へ移した。本モジュールは「lit/tunnelタグ→
材料フラグ」の解決（`night_materials`）だけを担う。配列版（旧`night_difficulty_array`）は
`evaluate_axis_array`（同一定義から導出）へ置き換えたため削除した。

改善計画T320: スカラー版の互換ラッパ`night_difficulty`（`evaluate_axis_scalar(
AXIS_DEFINITIONS["night"], night_materials(tags))`を1行呼ぶだけの薄い関数）は、
実行時経路のどこからも呼ばれておらずテストのみが参照していたため削除した
（実行時経路は`evaluate_axis_difficulties`/`compute_edge_axis_scores`を通じて
`night_materials`の結果を直接評価する経路を使っており、この関数を経由していなかった）。
"""

from app.domain.recipe import tag_value_is


def night_materials(tags: dict[str, str] | None) -> dict[str, bool | None]:
    """way_tagsからnight軸の材料フラグ（lit/has_tunnel）を解決する。`tags`がNone
    （way_tags未取得、他の材料タグ依存関数と同じ「データ無し」の表現）なら両方None
    （＝night軸は評価されない）。"""
    if tags is None:
        return {"lit": None, "has_tunnel": None}
    return {
        "lit": tag_value_is(tags, "lit", "yes"),
        "has_tunnel": tag_value_is(tags, "tunnel", "yes"),
    }
