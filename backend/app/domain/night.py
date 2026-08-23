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
夜間ライドの実用上望ましいと判断した）。既定重み`night_weight=0.0`（設計プロンプトの
指示どおり）のため、この判断が既定の経路・スコアに影響することはない。
"""

from app.domain.axis_templates import evaluate_flag_sum
from app.domain.recipe import tag_value_is

_NO_LIT_SCORE = 50.0
_TUNNEL_SCORE = 50.0
_NIGHT_DIFFICULTY_CAP = 100.0


def night_difficulty(tags: dict[str, str] | None) -> float | None:
    """街灯なし・トンネルの有無から夜間の走りにくさ(0-100)を算出する。`tags`がNone
    （way_tags未取得、他の材料タグ依存関数と同じ「データ無し」の表現）ならNone。

    「フラグ加算」テンプレート（改善計画T221 Stage A、T239）: 街灯なし・トンネルの
    2フラグそれぞれに固定加点し合計する（`evaluate_flag_sum`）。
    """
    if tags is None:
        return None
    no_lit = not tag_value_is(tags, "lit", "yes")
    has_tunnel = tag_value_is(tags, "tunnel", "yes")
    return evaluate_flag_sum([(no_lit, _NO_LIT_SCORE), (has_tunnel, _TUNNEL_SCORE)], cap=_NIGHT_DIFFICULTY_CAP)
