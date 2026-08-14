def normalize_min_max(values: list[float | None], higher_is_better: bool) -> list[float | None]:
    """候補集合内でmin-max正規化し0-100点に変換する。

    絶対的なしきい値を決め打ちできる実データが無いため、同じ`generate_loops`呼び出し内の
    候補同士を相対比較するためのスコアとして設計している（異なるリクエスト間では比較不可）。
    `None`はそのまま`None`を返す（そのメトリクスが取得できなかった候補は合成時に除外するため）。
    全候補が同値の場合は差をつけられないため中立の100点を返す。
    """
    present = [v for v in values if v is not None]
    if not present:
        return [None] * len(values)

    lo, hi = min(present), max(present)

    def scale(value: float | None) -> float | None:
        if value is None:
            return None
        if lo == hi:
            return 100.0
        ratio = (value - lo) / (hi - lo)
        if not higher_is_better:
            ratio = 1 - ratio
        return round(ratio * 100, 1)

    return [scale(v) for v in values]
