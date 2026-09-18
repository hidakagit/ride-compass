"""measure_vending_types.pyの純粋関数（PBF I/Oから独立した集計・分類）のテスト。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from measure_vending_types import VendingCounter, classify  # noqa: E402


def test_classify_treats_drink_machines_as_supply():
    assert classify("drinks") == "補給に使える"
    assert classify("beverages") == "補給に使える"


def test_classify_splits_multi_values_and_accepts_any_supply_member():
    """複数の値は`;`で連結される。1つでも口に入るものがあれば補給に使える。"""
    assert classify("cigarettes;drinks") == "補給に使える"
    assert classify("drinks;food") == "補給に使える"


def test_classify_is_case_and_space_insensitive():
    assert classify(" Drinks ") == "補給に使える"


def test_classify_rejects_machines_that_sell_nothing_edible():
    assert classify("parking_tickets") == "補給に使えない"
    assert classify("cigarettes") == "補給に使えない"


def test_classify_keeps_missing_tag_as_unknown():
    """タグ無しを「使えない」へ寄せない。寄せると絞り込みの効果を過大に見積もる。"""
    assert classify(None) == "不明（vendingタグ無し）"
    assert classify("") == "不明（vendingタグ無し）"
    # 空白だけ・区切り記号だけの値も「値が無い」と同じ扱いにする（使えない側へ数えない）。
    assert classify("   ") == "不明（vendingタグ無し）"
    assert classify(";;") == "不明（vendingタグ無し）"


def test_counter_reports_each_class_and_value_distribution():
    counter = VendingCounter()
    for tags in ({"vending": "drinks"}, {"vending": "drinks"}, {"vending": "cigarettes"}, {}):
        counter.add(tags)

    assert counter.total == 4
    lines = "\n".join(counter.report_lines(top=10))
    assert "amenity=vending_machine: 4件" in lines
    assert "補給に使える: 2件（50.0%）" in lines
    assert "補給に使えない: 1件（25.0%）" in lines
    assert "不明（vendingタグ無し）: 1件（25.0%）" in lines
    assert "drinks: 2件（50.0%）" in lines
    assert "(タグ無し): 1件（25.0%）" in lines


def test_counter_reports_empty_population_explicitly():
    """0件を0%の表として出さない（測れていないことが読み取れるようにする）。"""
    assert VendingCounter().report_lines(top=10) == ["（amenity=vending_machineのnodeが見つかりませんでした）"]
