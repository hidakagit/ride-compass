"""軸スタジオが実データを見て設定を決めるための読み出し（分布プレビュー・材料の値の一覧）。

折れ点や重みを編集している最中に、**その設定で実データがどう分布するか**を返す。
軸スタジオは数値の入力欄を並べるだけでは折れ点の妥当性を判断できず、公開して地図と
ルートを見るまで結果が分からない。

返すのは**折れ点を通す前の生値**（`terms`の重み付き和）の分布で、折れ点そのものは
フロント側が局所的に当てはめる——折れ点を1つ動かすたびに通信すると編集の手応えが
失われるうえ、折れ点は区分線形の写像でしかなく、生値のヒストグラムがあれば
クライアントで正確に求まる。

母集団はWay単位（道の生データの抽選サンプル）。
"""

import logging
from typing import SupportsFloat, cast

from cachetools import TTLCache

from app.domain.axis_definitions import AxisShape, raw_values, referenced_materials
from app.domain.material_catalog import material_dtype
from app.domain.region import BoundingBox
from app.domain.value_distribution import ValueDistribution, ValueSpread, weighted_distribution, weighted_spread
from app.infrastructure.database import DB_UNAVAILABLE_ERRORS
from app.infrastructure.debug_log import log_external_call, mark_failed
from app.infrastructure.road_graph_repository import RoadGraphRepository

logger = logging.getLogger("ridecompass.axis_preview")

# 抽選の広さ。ページ単位の抽選（TABLESAMPLE SYSTEM）のため、狭すぎると地理的に偏る。
SAMPLE_PERCENT = 2.0
SAMPLE_LIMIT = 20_000

# サンプルの保持時間。編集中は同じサンプルを使い回して即応させ、取込・集計バッチの後は
# 自然に入れ替わる程度の長さにする。
_SAMPLE_TTL_SECONDS = 15 * 60
_sample_cache: TTLCache = TTLCache(maxsize=1, ttl=_SAMPLE_TTL_SECONDS)


async def load_way_sample(
    repository: RoadGraphRepository,
    sample_percent: float,
    limit: int,
    bbox: BoundingBox | None = None,
) -> list[tuple[float, dict[str, object]]]:
    """way標本を`(延長m, 材料値)`の並びで返す。`bbox`を渡すとその範囲内だけを対象にする。

    分布プレビューと飽和度の実測スクリプト（`backend/scripts/measure_axis_saturation.py`）が
    同じ標本の作り方を共有するための口。
    """
    accident_years = await repository.get_accident_years_covered()
    return await repository.sample_way_material_values(
        accident_years, sample_percent, limit, bbox
    )


async def _load_sample(repository: RoadGraphRepository) -> list[tuple[float, dict[str, object]]]:
    cached = _sample_cache.get("sample")
    if cached is not None:
        return cached
    sample = await load_way_sample(repository, SAMPLE_PERCENT, SAMPLE_LIMIT)
    _sample_cache["sample"] = sample
    logger.info("軸プレビューのサンプルを取得 ways=%d", len(sample))
    return sample


async def axis_raw_value_distribution(
    repository: RoadGraphRepository, shape: AxisShape
) -> ValueDistribution:
    """候補の`shape`の生値（折れ点を通す前）の分布。"""
    return raw_value_distribution(shape, await _load_sample(repository))


def raw_value_distribution(shape: AxisShape, sample: list[tuple[float, dict[str, object]]]) -> ValueDistribution:
    """道の標本（`(長さm, 材料id→値)`）から、`shape`の生値の延長で重み付けた分布。生値を出せない道は数えない。"""
    material_ids = referenced_materials(shape, [])
    values = raw_values(
        shape, {m: [materials.get(m) for _, materials in sample] for m in material_ids}, len(sample)
    )
    pairs = [(length_m, value) for (length_m, _), value in zip(sample, values) if value is not None]
    return weighted_distribution(pairs)


async def material_value_distribution(repository: RoadGraphRepository, material_id: str) -> ValueSpread | None:
    """1材料の値の分位点とゼロの割合。数値材料のみ（真偽・カテゴリは分位に意味が無いためNone）。"""
    if material_dtype(material_id) != "numeric":
        return None
    sample = await _load_sample(repository)
    pairs = [
        (length_m, float(cast(SupportsFloat, materials[material_id])))
        for length_m, materials in sample
        if materials.get(material_id) is not None
    ]
    return weighted_spread(pairs)


async def material_values(repository: RoadGraphRepository, material_id: str) -> list[str] | None:
    """指定した材料についてDBへ実際に取り込まれている値の一覧。軸スタジオの値入力が使う。

    索引の効かない`SELECT DISTINCT`（実質全表走査）なので、`repository`はルート生成用の長い
    `command_timeout`のセッションで渡す（`api/dependencies.py: get_road_graph_repository`）。

    **取得できなかったとき（DB例外・タイムアウト）はNone**、取得できて値が無いときは空リスト。
    両方を空リストへ倒すと、画面は「候補が無い」と「候補を出せなかった」を区別できず、
    DBのタイムアウトが「この材料には値が無い」として静かに表示される。
    """
    with log_external_call("axis-preview:material-values", material_id=material_id) as fields:
        try:
            values = await repository.get_distinct_material_values(material_id)
        except DB_UNAVAILABLE_ERRORS as exc:
            mark_failed(fields, exc)
            return None
        fields["value_count"] = len(values)
        return values
