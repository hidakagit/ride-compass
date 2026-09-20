"""タグ分類の**規則そのもの**（`domain/traffic.py`の表）。

規則をDBへ渡して実際に引き当てた結果は`test_tag_classification.py`が見る。こちらは
DBを要らずに回り、「表に何が載っているか」だけを押さえる——載せてはいけない値を
足したときに、DBを立てなくても落ちる。
"""

from typing import get_args

from app.domain.traffic import (
    DIRECTION_RULES,
    STOP_POI_KINDS,
    TAG_KIND_RULES,
    StopPoiKind,
)


def kinds_for(tag_key: str) -> dict[str, str]:
    return {value: kind for key, value, kind, _ in TAG_KIND_RULES if key == tag_key}


def test_stop_poi_kinds_matches_literal_values():
    """`STOP_POI_KINDS`（SQL側kindフィルタの正準集合）が`StopPoiKind`と乖離しないこと。"""
    assert STOP_POI_KINDS == frozenset(get_args(StopPoiKind))


def test_barrier_values_deliberately_left_out_are_not_in_the_rules():
    """`_BARRIER_STOP_VALUES`から**意図的に外した**値（traffic.pyのコメント参照）。

    ここを固定しないと、`kerb`のような「該当件数が多いが停止要因として識別力が無い」値を
    足しても1件も落ちず、停止密度だけが実データで跳ね上がる。
    """
    barriers = kinds_for("barrier")
    for value in ("kerb", "toll_booth", "entrance", "fence", "wall",
                  "guard_rail", "jersey_barrier"):
        assert value not in barriers, value


def test_traffic_calming_values_deliberately_left_out():
    # island（中央島）・noは進行を妨げない。
    calming = kinds_for("traffic_calming")
    for value in ("island", "no"):
        assert value not in calming, value


def test_stop_factors_are_looked_up_before_supply():
    """停止要因の規則が、補給・休憩より先に当たること（優先順位は`priority`列が持つ）。"""
    stop_keys = {"railway", "highway", "barrier", "traffic_calming"}
    stop = [p for key, _, _, p in TAG_KIND_RULES if key in stop_keys]
    supply = [p for key, _, _, p in TAG_KIND_RULES if key not in stop_keys]
    assert max(stop) < min(supply)


def test_oneway_bicycle_is_looked_up_before_oneway():
    """自転車に限った例外タグが、`oneway`本体より先に当たること。"""
    bicycle = [p for key, _, _, p in DIRECTION_RULES if key == "oneway:bicycle"]
    plain = [p for key, _, _, p in DIRECTION_RULES if key == "oneway"]
    junction = [p for key, _, _, p in DIRECTION_RULES if key == "junction"]
    assert max(bicycle) < min(plain)
    assert max(plain) < min(junction)


def test_rules_do_not_contain_duplicate_keys():
    """同じ(タグ名, 値)が2つの種別へ引き当たらないこと。どちらが勝つかが順序に依存する。"""
    for rules in (TAG_KIND_RULES, DIRECTION_RULES):
        pairs = [(key, value) for key, value, _, _ in rules]
        assert len(pairs) == len(set(pairs))
