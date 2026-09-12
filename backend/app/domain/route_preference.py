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
    """Evaluation Engineが使う重み（仕様書27章）。

    `weights`はaxis_id（`domain/axis_definitions.py: AXIS_DEFINITIONS`のキー）をキーとする
    重み辞書。軸の増減はAXIS_DEFINITIONSの変更だけで本モデルへ自動反映される。

    `weights`は部分指定を許す（不足キーは各軸の`default_weight`で補完。ドメイン内部・
    テストの利便のため）。未知のキーはエラー。**API境界の「上書きするなら全軸を明示する」
    検証は`api/routers/routes.py: RoutePreferenceWeights`が担う**（省略時にクラス既定値が
    黙って入ることを避けるため）。
    """

    weights: dict[str, float] = Field(default_factory=default_axis_weights)

    @model_validator(mode="after")
    def _validate_and_fill_weights(self) -> "RoutePreference":
        # 内部軸（is_published=False、他の公開軸から参照される専用の推定軸）は
        # 一般ユーザー・リクエストからの重み付け対象外。3次合成
        # （compute_edge_costs_bulk側）も公開軸のみをループするため、weights辞書の
        # キー集合をここで揃えておく。
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
        汚染しないための生成ヘルパー）。

        `axis_id`が現在の`weights`（＝現在の公開軸集合、`default_axis_weights()`参照）に
        無い場合は無変更の`self`をそのまま返す（差し替え対象の軸自体が存在しない以上、
        差し替える意味も無いため）。
        """
        if axis_id not in self.weights:
            return self
        return RoutePreference(weights={**self.weights, axis_id: value})

    def with_time_scope(self, active_scopes: frozenset[str] = frozenset()) -> "RoutePreference":
        """time_scope（AXIS_DEFINITIONS参照）が"always"以外の軸のうち、
        `active_scopes`に含まれないものの重みを0倍にしたコピーを返す（`with_weight`と
        同じくリクエスト間で共有するインスタンスを汚染しない生成ヘルパー）。"""
        overridden = time_scoped_weights(self.weights, active_scopes)
        if overridden == self.weights:
            return self
        return RoutePreference(weights=overridden)
