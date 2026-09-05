"""夜間（街灯なし・トンネル）の材料タグから難易度への変換（改善計画T139）。

安全度軸の廃止（`domain/safety.py`、モジュール自体の削除はT148で完了済み）に伴い、
街灯・トンネルの寄与を独立した軸として切り出した。旧`SafetyRecipe.lit_adjustment`/
`tunnel_adjustment`は
「lit=yesなら安全側へ-1」という報酬方向の補正だったが、こちらは他の`*_difficulty`関数と
同じ「走りにくさ0-100、大きいほど大変」の絶対基準に合わせ、"街灯なし"をペナルティとして
加点する方向に符号を反転させている（走りにくさの向きを他軸と揃えるための符号反転であり、
判定基準自体は変えていない）。

`lit`タグ不在は「街灯なしとみなす」（unknown safeの原則から外れる意図的な選択。litタグは
明示的に付与されている場合のみ確認できる情報で、多くのwayは単にタグが無いだけだが、
「街灯があるかどうか分からない区間」を「街灯ありと同等に扱う」よりは安全側に倒すほうが
夜間ライドの実用上望ましいと判断した）。既定重み`night`＝0.0（`domain/axis_definitions.py`）
のため、この判断が既定の経路・スコアに影響することはない。

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
    """way_tagsからnight軸の材料フラグ（lit/no_lit/has_tunnel）を解決する。`tags`がNone
    （way_tags未取得、他の材料タグ依存関数と同じ「データ無し」の表現）なら全てNone
    （＝night軸は評価されない）。no_litはlitの否定を返す非推奨エイリアス——公開済みの
    夜間軸定義がまだno_litをmaterialとして参照しているため、DB側の軸定義をlit材料へ
    移行するまで両方のキーを提供する（domain/material_catalog.py: MATERIAL_CATALOG["no_lit"]
    参照）。"""
    if tags is None:
        return {"lit": None, "no_lit": None, "has_tunnel": None}
    is_lit = tag_value_is(tags, "lit", "yes")
    return {
        "lit": is_lit,
        "no_lit": not is_lit,
        "has_tunnel": tag_value_is(tags, "tunnel", "yes"),
    }
