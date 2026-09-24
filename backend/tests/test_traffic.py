"""`domain/traffic.py`——道の階級（交差点の優先関係）と、停止要因の待ち（所要時間への足し方）。

ここで見ないもの:
- 点のタグから停止要因・補給休憩の種別を引き当てるSQL → `test_tag_classification.py`
- 道の通行方向を決めるSQL → `test_resolve_direction.py`
- 停止要因の種別を画面の見出しへ写すこと → `test_primary_attribute_display.py`
- 階級を交差点の待ちへ使うこと（待ちの要る階級の下限を含む） → `test_routing.py`

階級の値そのものに意味は無く、比較の結果だけが使われる。表の中身は書き写さず、表から導いた
母集団（ランプ全件・表に無い値）に対して成り立つことだけを見る。
停止の待ちの秒数は較正値の読み出し（`tuning_value`）を差し替えて与える。
"""

import pytest

from app.domain import traffic
from tests.bound_fake import bound

# ---- 道の階級 ----


def test_every_link_road_ranks_with_its_main_road():
    # 母集団は階級表から取る: ランプ（`_link`）は本線と同じ扱い。分けると合流の待ちの判定が本線とずれる
    links = [highway for highway in traffic.HIGHWAY_RANK if highway.endswith("_link")]
    assert links, "階級表にランプが1つも無い"

    for link in links:
        assert traffic.highway_rank(link) == traffic.highway_rank(link.removesuffix("_link"))


@pytest.mark.parametrize("highway", [None, "", "not_a_highway_value"])
def test_a_value_missing_from_the_table_ranks_below_every_road_in_it(highway):
    # 自転車道・歩道・未知の値は表に無く、どの道より下になる（交差点で「上位の道と交わる」側に立たない）
    assert highway not in traffic.HIGHWAY_RANK
    assert traffic.highway_rank(highway) < min(traffic.HIGHWAY_RANK.values())


# ---- 停止要因の待ち ----


@pytest.fixture
def stop_values(monkeypatch):
    """種別ごとに別の秒数を持つ較正値。書き換えると次の呼び出しから効く。"""
    values = {traffic.stop_seconds_parameter_id(kind): float(i) for i, kind in enumerate(traffic.POI_COUNT_KINDS)}
    monkeypatch.setattr(traffic, "tuning_value", bound(traffic.tuning_value, lambda param_id: values[param_id]))
    return values


def test_each_counted_kind_reads_its_own_waiting_time(stop_values):
    kinds = list(traffic.POI_COUNT_KINDS)
    assert kinds, "数える停止要因の種別が無い"

    assert [traffic.stop_seconds(kind) for kind in kinds] == [float(i) for i in range(len(kinds))]


def test_the_waiting_time_is_read_each_time(stop_values):
    kind = next(iter(traffic.POI_COUNT_KINDS))
    stop_values[traffic.stop_seconds_parameter_id(kind)] = 42.0

    # 管理画面で変えた秒数は、次の所要時間の計算から効く
    assert traffic.stop_seconds(kind) == 42.0


def test_there_is_one_waiting_material_per_counted_kind_in_the_same_order():
    # 所要時間の合成は種別と材料を並びで対にする（`zip(..., strict=True)`）
    kinds = list(traffic.POI_COUNT_KINDS)
    materials = traffic.stop_count_material_ids()

    assert len(materials) == len(kinds)
    assert len(set(materials)) == len(materials)
    assert all(kind in material for kind, material in zip(kinds, materials))
