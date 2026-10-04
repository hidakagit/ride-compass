"""`domain/traffic.py`のうち、Pythonで値を返す入口——停止要因の待ち（`stop_seconds`）と道の階級（`highway_rank`）。

ここで見ないもの:
- 点のタグから停止要因・補給休憩の種別を引き当てるSQLと、数える種別へ畳むSQL → `test_tag_classification.py`
- 道の通行方向を決めるSQL → `test_resolve_direction.py`
- 停止の待ちが区間の所要時間へ足されること → `test_leg_costs.py`
- 階級を比べて交差点の待ちを足すこと → `test_routing.py`
- 停止要因の種別を地図の凡例の行へ写すこと → `test_material_catalog.py`
"""

import pytest

from app.domain import traffic
from app.domain.tuning import TUNING_VALUES


def test_the_wait_of_a_stop_follows_the_value_changed_from_the_admin_screen(monkeypatch):
    """待ちの秒は呼ぶたびに読む。管理画面から変えた値が、プロセスを入れ替えずに次の生成から効く。"""
    monkeypatch.setitem(TUNING_VALUES, traffic.stop_seconds_parameter_id("signal"), 33.0)

    assert traffic.stop_seconds("signal") == 33.0


def test_a_kind_that_is_not_counted_fails_instead_of_waiting_zero_seconds():
    with pytest.raises(KeyError):
        traffic.stop_seconds("traffic_signals")


# OSMの道路の格（Key:highway）の上から順。リンク（`*_link`）は本線と同じ格に並ぶ。
_OSM_MAIN_ROADS = ["motorway", "trunk", "primary", "secondary", "tertiary"]


def test_the_rank_follows_the_osm_road_hierarchy():
    ranks = [traffic.highway_rank(highway) for highway in _OSM_MAIN_ROADS]

    assert ranks == sorted(ranks, reverse=True)
    assert len(set(ranks)) == len(ranks)


@pytest.mark.parametrize("highway", _OSM_MAIN_ROADS)
def test_a_link_road_has_the_rank_of_its_main_road(highway):
    """ランプを本線より下に置くと、本線とランプが合流する所で「上位の道と交わる」待ちが付く。"""
    assert traffic.highway_rank(f"{highway}_link") == traffic.highway_rank(highway)


def test_minor_roads_share_one_rank_below_tertiary_and_above_paths():
    minor = {traffic.highway_rank(h) for h in ("unclassified", "residential", "living_street", "service")}

    assert len(minor) == 1
    assert traffic.highway_rank("cycleway") < minor.pop() < traffic.highway_rank("tertiary")


@pytest.mark.parametrize("highway", ["cycleway", None])
def test_paths_unknown_values_and_missing_tags_rank_lowest(highway):
    assert traffic.highway_rank(highway) == 0


def test_only_roads_from_tertiary_up_need_a_wait_to_cross():
    """生活道路・サービス道路を横切るのに待ちは要らない。自転車道（階級0）からサービス道路へ出るだけで
    「上位の道を渡る」と数えないこと。"""
    assert traffic.highway_rank("tertiary") >= traffic.MAJOR_CROSSING_MIN_RANK
    assert traffic.highway_rank("service") < traffic.MAJOR_CROSSING_MIN_RANK
