"""ルート生成リクエストの重み指定（`RoutePreference`）。

評価そのもの（`domain/evaluation.py`）とは変更理由が異なる——ここが変わるのは
APIが受け取る形を変えるときで、Edge Costの計算方法を変えるときではない。
"""

from collections.abc import Mapping

from pydantic import Field, model_validator

from app.domain.axis_definitions import (
    AXIS_DEFINITIONS,
    default_axis_weights,
    time_scoped_weights,
)
from app.domain.strict_model import StrictModel

#: 重みの配分を画面で調整するとき、1軸へ寄せられる上限。要求の検証には使わない——既定の重みや
#: 保存された配分がこれを超えていても生成は受け付ける。
MAX_AXIS_WEIGHT = 0.6


def published_axis_ids() -> set[str]:
    """重みを付けられる軸。内部軸（is_published=False、他の公開軸から参照される専用の推定軸）は
    重み付けの対象外で、3次合成も公開軸だけを回す。"""
    return {axis_id for axis_id, d in AXIS_DEFINITIONS.items() if d.is_published}


def check_axis_weights(weights: Mapping[str, float]) -> None:
    """重みの値の不変条件。書き手（ルート生成の要求・研究のスクリプト・テスト）を問わず成り立つ。

    キーは公開軸のidだけ。値は非負——負の重みは合成difficultyの分母（重みの総和）と分子の符号を
    食い違わせ、良い経路ほど高い点数になる。
    """
    known = published_axis_ids()
    unknown = sorted(set(weights) - known)
    if unknown:
        raise ValueError(f"unknown axis_id in weights: {unknown} (known: {sorted(known)})")
    negative = sorted(axis_id for axis_id, weight in weights.items() if weight < 0)
    if negative:
        raise ValueError(f"weights must be >= 0 (negative: {negative})")


class RoutePreference(StrictModel):
    """Evaluation Engineが使う、axis_idをキーとする重み辞書。

    部分指定を許し、不足キーは各軸の`default_weight`で補完する。値の不変条件は`check_axis_weights`。
    **API境界の「上書きするなら全軸を明示する」検証は`api/routers/routes.py:
    RoutePreferenceWeights`が担う**（省略時にクラス既定値が黙って入ることを避けるため）。
    """

    weights: dict[str, float] = Field(default_factory=default_axis_weights)

    @model_validator(mode="after")
    def _validate_and_fill_weights(self) -> "RoutePreference":
        check_axis_weights(self.weights)
        published = published_axis_ids()
        merged = default_axis_weights()
        merged.update(self.weights)
        # キー順をAXIS_DEFINITIONSの定義順（＝合成の加算順）へ正規化する。
        self.weights = {axis_id: merged[axis_id] for axis_id in AXIS_DEFINITIONS if axis_id in published}
        return self

    def with_time_scope(self, active_scopes: frozenset[str]) -> "RoutePreference":
        """time_scopeが"always"以外の軸のうち、`active_scopes`に含まれないものの重みを
        0倍にしたコピーを返す。

        既定値を持たせない——空集合を省略できると、渡し忘れた呼び出しが「どの時間帯にも
        当たらない」として夜間軸等を黙って0倍にする。
        """
        overridden = time_scoped_weights(self.weights, active_scopes)
        if overridden == self.weights:
            return self
        return RoutePreference(weights=overridden)
