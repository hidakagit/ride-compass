"""標高統計（gain/min/max/max_gradient）の最終集約パターン。

`RoadGraphEngine._aggregate_elevation`が、バッチ事前計算済みの`ElevationAttribute`を
Edge単位で集約する際に使う。「数値のリストから合計/最小/最大を求め、空なら`None`、
そうでなければ小数1桁へ丸める」という集約パターンをここへ集約する。
"""


def _round_or_none(value: float | None) -> float | None:
    return None if value is None else round(value, 1)


def sum_or_none(values: list[float]) -> float | None:
    return _round_or_none(sum(values)) if values else None


def min_or_none(values: list[float]) -> float | None:
    return _round_or_none(min(values)) if values else None


def max_or_none(values: list[float]) -> float | None:
    return _round_or_none(max(values)) if values else None
