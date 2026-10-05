"""延長で重み付けた値の分布（分位点とヒストグラム）と、値の範囲の手がかり（分位点とゼロの割合）。
軸スタジオの分布の口・材料の分布の口の応答の型を兼ねる。

本数ではなく**延長で重み付ける**。本数で数えると短い道が多数を占めて実際に走る距離の感覚と合わない。
"""

import numpy as np

from app.domain.strict_model import StrictModel

# 生値のヒストグラムの階級数。フロントが折れ点を当てはめる粒度で、細かすぎても
# 画面上の意味が増えない。
HISTOGRAM_BINS = 60


class ValueDistribution(StrictModel):
    """延長で重み付けた分布。`bins`は`(下限, 上限, その階級が占める延長の割合)`。

    `bins`の範囲はデータの値域から決まり、**負の生値を持つ軸では下限も負になる**
    （0は常に範囲へ含む）。消費側が「下限は常に0」を前提にしないこと。
    """

    sample_ways: int
    total_km: float
    quantiles: dict[str, float]
    bins: list[tuple[float, float, float]]


EMPTY_DISTRIBUTION = ValueDistribution(sample_ways=0, total_km=0.0, quantiles={}, bins=[])


class ValueSpread(StrictModel):
    """延長で重み付けた分位点と、値がちょうど0である延長の割合（負の値は含まない）。"""

    quantiles: dict[str, float]
    zero_share: float


EMPTY_SPREAD = ValueSpread(quantiles={}, zero_share=0.0)

_QUANTILE_TARGETS = [("p10", 0.10), ("p25", 0.25), ("p50", 0.50), ("p75", 0.75), ("p90", 0.90), ("p99", 0.99)]


def weighted_quantiles(
    pairs: list[tuple[float, float]], targets: list[tuple[str, float]], digits: int
) -> dict[str, float]:
    """`(延長m, 値)`から延長で重み付けた分位点を返す（累積の延長の割合が初めて比率に達する値）。"""
    if not pairs:
        return {}
    lengths, values = np.asarray(pairs, dtype=float).T
    points = np.quantile(values, [q for _, q in targets], weights=lengths, method="inverted_cdf")
    # `round`はnumpyの浮動小数へ当てると`np.round`になり、端数がちょうど`.x5`の値を別の側へ丸める。
    return {name: round(float(point), digits) for (name, _), point in zip(targets, points, strict=True)}


def weighted_distribution(pairs: list[tuple[float, float]]) -> ValueDistribution:
    """`(長さm, 値)`から延長で重み付けた分布を組み立てる。"""
    if not pairs:
        return EMPTY_DISTRIBUTION
    lengths, values = np.asarray(pairs, dtype=float).T
    total_m = float(lengths.sum())
    quantiles = weighted_quantiles(pairs, _QUANTILE_TARGETS, digits=3)

    # 描画範囲は**データの値域から決める**。下限を0に固定すると、生値が負になる軸
    # （termsの重みがすべて負の軸）で全サンプルが階級0へ潰れ、「1本だけの棒＝全量が
    # 同じ値」という実態と異なる分布になる。0は常に範囲へ含める（「値0の道がどれだけ
    # あるか」は折れ点を当てる際の基準になる）。
    lower = min(0.0, float(values.min()))
    # 上端の外れ値でヒストグラムが潰れないよう、p99の少し上までを描画範囲にする
    # （下端側は分位を持たないためデータ下端をそのまま使う）。
    upper = quantiles["p99"] * 1.2 if quantiles["p99"] > 0 else max(0.0, float(values.max()))
    span = upper - lower
    if span <= 0:
        # 全サンプルが同じ値（かつ0）のとき。幅0だと除算できないため名目上の1を置く。
        span = 1.0
    width = span / HISTOGRAM_BINS
    # 描画範囲の外（p99の上の外れ値）は端の階級へ寄せる。捨てると割合の合計が1に満たない。
    indices = np.clip(((values - lower) / width).astype(int), 0, HISTOGRAM_BINS - 1)
    buckets = np.bincount(indices, weights=lengths, minlength=HISTOGRAM_BINS)
    edges = lower + np.arange(HISTOGRAM_BINS + 1) * width
    bins = [
        (round(float(low), 4), round(float(high), 4), round(float(b) / total_m, 5))
        for low, high, b in zip(edges[:-1], edges[1:], buckets, strict=True)
    ]
    return ValueDistribution(
        sample_ways=len(pairs),
        total_km=round(total_m / 1000, 1),
        quantiles=quantiles,
        bins=bins,
    )


def weighted_spread(pairs: list[tuple[float, float]]) -> ValueSpread:
    """`(長さm, 値)`から延長で重み付けた分位点とゼロの割合を求める。"""
    if not pairs:
        return EMPTY_SPREAD
    lengths, values = np.asarray(pairs, dtype=float).T
    # 「ゼロ」は値がちょうど0であること。`v <= 0`にすると負の値を持つ材料で
    # 「下り勾配の道」まで0として数えられ、表示（「ゼロX%」）が意味と食い違う。
    zero_share = float(lengths[values == 0].sum()) / float(lengths.sum())
    return ValueSpread(
        quantiles=weighted_quantiles(pairs, _QUANTILE_TARGETS, digits=3), zero_share=round(zero_share, 5)
    )
