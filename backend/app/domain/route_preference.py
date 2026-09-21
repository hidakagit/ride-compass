"""ルート生成リクエストの重み指定（`RoutePreference`）。

評価そのもの（`domain/evaluation.py`）とは変更理由が異なる——ここが変わるのは
APIが受け取る形を変えるときで、Edge Costの計算方法を変えるときではない。
"""

from pydantic import Field, model_validator

from app.domain.axis_definitions import (
    AXIS_DEFINITIONS,
    default_axis_weights,
    time_scoped_weights,
)
from app.domain.strict_model import StrictModel


class RoutePreference(StrictModel):
    """Evaluation Engineが使う、axis_idをキーとする重み辞書。

    部分指定を許し、不足キーは各軸の`default_weight`で補完する。未知のキーはエラー。
    **API境界の「上書きするなら全軸を明示する」検証は`api/routers/routes.py:
    RoutePreferenceWeights`が担う**（省略時にクラス既定値が黙って入ることを避けるため）。
    """

    weights: dict[str, float] = Field(default_factory=default_axis_weights)

    @model_validator(mode="after")
    def _validate_and_fill_weights(self) -> "RoutePreference":
        # 内部軸（is_published=False、他の公開軸から参照される専用の推定軸）は
        # リクエストからの重み付け対象外。3次合成も公開軸のみをループするため、
        # weights辞書のキー集合をここで揃えておく。
        published_axis_ids = {axis_id for axis_id, d in AXIS_DEFINITIONS.items() if d.is_published}
        unknown = sorted(set(self.weights) - published_axis_ids)
        if unknown:
            raise ValueError(f"unknown axis_id in weights: {unknown} (known: {sorted(published_axis_ids)})")
        merged = default_axis_weights()
        merged.update(self.weights)
        # キー順をAXIS_DEFINITIONSの定義順（＝合成の加算順）へ正規化する。
        self.weights = {axis_id: merged[axis_id] for axis_id in AXIS_DEFINITIONS if axis_id in published_axis_ids}
        return self

    def with_weight(self, axis_id: str, value: float) -> "RoutePreference":
        """1軸の重みだけを差し替えたコピーを返す（リクエスト間で共有するインスタンスを
        汚染しないための生成ヘルパー）。公開軸に無い`axis_id`なら無変更の`self`を返す。
        """
        if axis_id not in self.weights:
            return self
        return RoutePreference(weights={**self.weights, axis_id: value})

    def with_time_scope(self, active_scopes: frozenset[str] = frozenset()) -> "RoutePreference":
        """time_scopeが"always"以外の軸のうち、`active_scopes`に含まれないものの重みを
        0倍にしたコピーを返す。"""
        overridden = time_scoped_weights(self.weights, active_scopes)
        if overridden == self.weights:
            return self
        return RoutePreference(weights=overridden)
