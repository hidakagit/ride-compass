"""標高統計（gain/min/max/max_gradient）の最終集約パターンを共有する。

`ElevationService.get_profile`（GSI点サンプリングから自前でgain/gradientを算出する
openrouteserviceエンジン用）と`RoadGraphEngine._aggregate_elevation`（バッチ事前計算済み
`ElevationAttribute`をEdge単位で集約するroad_graphエンジン用）は、標高値そのものの
算出方法（点列から都度計算 / 事前計算済み値を読むだけ）が全く異なる別実装のままで正しい
（前者は`app.batch.precompute_elevation_attributes`が事前計算しない任意の点列を扱うため
リクエスト単位でGSIへ問い合わせる必要があり、後者はリクエスト単位のレイテンシへ外部API
呼び出しを持ち込まない設計上、道路網全体を対象にバッチ事前計算した値のみを読む）。
一方で両者とも最終的に「数値のリストから合計/最小/最大を求め、空なら`None`、
そうでなければ小数1桁へ丸める」という同じ集約パターンを個別実装していた
（デッドコード監査で重複と判明）ため、この末尾の集約部分だけを共有する。
"""


def _round_or_none(value: float | None) -> float | None:
    return None if value is None else round(value, 1)


def sum_or_none(values: list[float]) -> float | None:
    return _round_or_none(sum(values)) if values else None


def min_or_none(values: list[float]) -> float | None:
    return _round_or_none(min(values)) if values else None


def max_or_none(values: list[float]) -> float | None:
    return _round_or_none(max(values)) if values else None
