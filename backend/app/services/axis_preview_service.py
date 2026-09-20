"""軸スタジオの分布プレビュー。

折れ点や重みを編集している最中に、**その設定で実データがどう分布するか**を返す。
軸スタジオは数値の入力欄を並べるだけでは折れ点の妥当性を判断できず、公開して地図と
ルートを見るまで結果が分からない。

返すのは**折れ点を通す前の生値**（`terms`の重み付き和）の分布で、折れ点そのものは
フロント側が局所的に当てはめる——折れ点を1つ動かすたびに通信すると編集の手応えが
失われるうえ、折れ点は区分線形の写像でしかなく、生値のヒストグラムがあれば
クライアントで正確に求まる。

母集団はWay単位（`osm_raw_ways`の抽選サンプル）で、**延長で重み付ける**。本数で数えると
短い道が多数を占めて実際に走る距離の感覚と合わない。
"""

import logging
from dataclasses import dataclass

from cachetools import TTLCache

from app.domain.axis_definitions import AxisShape, BreakpointLinearShape
from app.domain.material_catalog import material_dtype
from app.domain.region import BoundingBox
from app.infrastructure.road_graph_repository import RoadGraphRepository

logger = logging.getLogger("ridecompass.axis_preview")

# 抽選の広さ。ページ単位の抽選（TABLESAMPLE SYSTEM）のため、狭すぎると地理的に偏る。
SAMPLE_PERCENT = 2.0
SAMPLE_LIMIT = 20_000

# サンプルの保持時間。編集中は同じサンプルを使い回して即応させ、取込・集計バッチの後は
# 自然に入れ替わる程度の長さにする。
_SAMPLE_TTL_SECONDS = 15 * 60
_sample_cache: TTLCache = TTLCache(maxsize=1, ttl=_SAMPLE_TTL_SECONDS)

# 生値のヒストグラムの階級数。フロントが折れ点を当てはめる粒度で、細かすぎても
# 画面上の意味が増えない。
HISTOGRAM_BINS = 60


@dataclass(frozen=True, slots=True)
class ValueDistribution:
    """延長で重み付けた分布。`bins`は`(下限, 上限, その階級が占める延長の割合)`。

    `bins`の範囲はデータの値域から決まり、**負の生値を持つ軸では下限も負になる**
    （0は常に範囲へ含む）。消費側が「下限は常に0」を前提にしないこと。
    """

    sample_ways: int
    total_km: float
    quantiles: dict[str, float]
    bins: list[tuple[float, float, float]]
    # 値がちょうど0である延長の割合（負の値は含まない）。
    zero_share: float


async def load_way_sample(
    repository: RoadGraphRepository,
    sample_percent: float,
    limit: int,
    bbox: BoundingBox | None = None,
) -> list[tuple[float, dict[str, object]]]:
    """way標本を`(延長m, 材料値)`の並びで返す。`bbox`を渡すとその範囲内だけを対象にする。

    分布プレビュー（このサービス）と飽和度の実測スクリプト
    （`backend/scripts/measure_axis_saturation.py`）が同じ標本の作り方を使う。
    """
    accident_years = await repository.get_accident_years_covered()
    return await repository.sample_way_material_values(
        accident_years, sample_percent, limit, bbox
    )


def weighted_quantiles(
    pairs: list[tuple[float, float]], targets: list[tuple[str, float]], digits: int
) -> dict[str, float]:
    """`(延長m, 値)`から延長で重み付けた分位点を返す（`targets`は比率の昇順）。

    値の並びを1回走査しながら累積比が各目標へ達した時点の値を採る。目標と丸め桁だけを
    引数にして、走査そのものは1つに保つ。
    """
    if not pairs:
        return {}
    total_m = sum(m for m, _ in pairs)
    ordered = sorted(pairs, key=lambda p: p[1])
    result: dict[str, float] = {}
    acc = 0.0
    index = 0
    for length_m, value in ordered:
        acc += length_m
        while index < len(targets) and acc / total_m >= targets[index][1]:
            result[targets[index][0]] = round(value, digits)
            index += 1
    while index < len(targets):
        result[targets[index][0]] = round(ordered[-1][1], digits)
        index += 1
    return result


async def _load_sample(repository: RoadGraphRepository) -> list[tuple[float, dict[str, object]]]:
    cached = _sample_cache.get("sample")
    if cached is not None:
        return cached
    sample = await load_way_sample(repository, SAMPLE_PERCENT, SAMPLE_LIMIT)
    _sample_cache["sample"] = sample
    logger.info("軸プレビューのサンプルを取得 ways=%d", len(sample))
    return sample


def _raw_value(shape: AxisShape, materials: dict[str, object]) -> float | None:
    """折れ点を通す前の生値。`BreakpointLinearShape`の`terms`の重み付き和と、
    `preprocess`（絶対値等）まで。categorical軸は生値の概念を持たないためNone。"""
    if not isinstance(shape, BreakpointLinearShape):
        return None
    total = 0.0
    seen = False
    for term in shape.terms:
        value = materials.get(term.material)
        if value is None:
            if term.required:
                return None
            continue
        seen = True
        total += float(value) * term.weight
    if not seen:
        return None
    if shape.preprocess == "abs":
        total = abs(total)
    return total


def _distribution(pairs: list[tuple[float, float]]) -> ValueDistribution:
    """`(長さm, 値)`から延長で重み付けた分布を組み立てる。"""
    if not pairs:
        return ValueDistribution(0, 0.0, {}, [], 0.0)
    total_m = sum(m for m, _ in pairs)
    ordered = sorted(pairs, key=lambda p: p[1])
    targets = [("p10", 0.10), ("p25", 0.25), ("p50", 0.50), ("p75", 0.75), ("p90", 0.90), ("p99", 0.99)]
    quantiles = weighted_quantiles(pairs, targets, digits=3)

    # 描画範囲は**データの値域から決める**。下限を0に固定すると、生値が負になる軸
    # （termsの重みがすべて負の軸。`bicycle_infra_quality`・`night`が該当する）で
    # 全サンプルが階級0へ潰れ、「1本だけの棒＝全量が同じ値」という
    # 実態と異なる分布になる。0は常に範囲へ含める（「値0の道がどれだけあるか」は
    # 折れ点を当てる際の基準になるため、片側に寄ったデータでも0の位置を見せる）。
    lower = min(0.0, ordered[0][1])
    # 上端の外れ値でヒストグラムが潰れないよう、p99の少し上までを描画範囲にする
    # （下端側は分位を持たないためデータ下端をそのまま使う）。
    upper = quantiles["p99"] * 1.2 if quantiles["p99"] > 0 else max(0.0, ordered[-1][1])
    span = upper - lower
    if span <= 0:
        # 全サンプルが同じ値（かつ0）のとき。幅0だと除算できないため名目上の1を置く。
        span = 1.0
        upper = lower + span
    width = span / HISTOGRAM_BINS
    buckets = [0.0] * HISTOGRAM_BINS
    for m, value in ordered:
        i = min(HISTOGRAM_BINS - 1, int((value - lower) / width))
        buckets[max(0, i)] += m
    bins = [
        (round(lower + i * width, 4), round(lower + (i + 1) * width, 4), round(b / total_m, 5))
        for i, b in enumerate(buckets)
    ]
    # 「ゼロ」は値がちょうど0であること。`v <= 0`にすると負の生値を持つ軸で
    # 「下り勾配の道」「開けていない道」まで0として数えられ、表示（「ゼロX%」）が
    # 意味と食い違う。
    zero_share = sum(m for m, v in ordered if v == 0) / total_m
    return ValueDistribution(
        sample_ways=len(pairs),
        total_km=round(total_m / 1000, 1),
        quantiles=quantiles,
        bins=bins,
        zero_share=round(zero_share, 5),
    )


async def axis_raw_value_distribution(
    repository: RoadGraphRepository, shape: AxisShape
) -> ValueDistribution:
    """候補の`shape`の生値（折れ点を通す前）の分布。"""
    sample = await _load_sample(repository)
    pairs = []
    for length_m, materials in sample:
        value = _raw_value(shape, materials)
        if value is not None:
            pairs.append((length_m, value))
    return _distribution(pairs)


async def material_value_distribution(
    repository: RoadGraphRepository, material_id: str
) -> ValueDistribution | None:
    """1材料の値の分布。数値材料のみ（真偽・カテゴリは分位に意味が無いためNone）。"""
    if material_dtype(material_id) != "numeric":
        return None
    sample = await _load_sample(repository)
    pairs = [
        (length_m, float(materials[material_id]))
        for length_m, materials in sample
        if materials.get(material_id) is not None
    ]
    return _distribution(pairs)

