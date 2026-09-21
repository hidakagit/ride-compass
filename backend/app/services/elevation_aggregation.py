def _round_or_none(value: float | None) -> float | None:
    return None if value is None else round(value, 1)


def sum_or_none(values: list[float]) -> float | None:
    return _round_or_none(sum(values)) if values else None


def min_or_none(values: list[float]) -> float | None:
    return _round_or_none(min(values)) if values else None


def max_or_none(values: list[float]) -> float | None:
    return _round_or_none(max(values)) if values else None
