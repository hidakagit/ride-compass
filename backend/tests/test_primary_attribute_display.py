"""一次属性の表示定義（`display_axes`）が、正準分類と食い違っていないこと。

**母集団は導出する**（設計原則 構造仕様12）——表示定義を持つ属性すべて、正準分類のタグ
すべてに対して回す。名指しした数件の検査は書かない。

この検査が守るのは「地図の色とルート評価の食い違い」である。表示の行が正準分類の一部を
取りこぼすと、その値の道は地図に出ないまま評価にだけ効く。逆に正準分類に無い値を行へ
書くと、その行は永久に空になる。どちらも例外にならず、画面を見ても気づけない。
"""

from typing import get_args

import pytest

from app.domain.display_palette import NOMINAL_SLOT_COUNT
from app.domain.material_catalog import PRIMARY_ATTRIBUTES
from app.domain.traffic import STOP_POI_KINDS, SupplyPoiKind
from app.domain.road import BAD_OSM_SURFACE_TAGS, GOOD_OSM_SURFACE_TAGS

DISPLAYED = [attr for attr in PRIMARY_ATTRIBUTES if attr.display_axes]


def _attr(attr_id: str):
    return next(attr for attr in PRIMARY_ATTRIBUTES if attr.attr_id == attr_id)


def _values(attr_id: str) -> set[object]:
    return {value for axis in _attr(attr_id).display_axes for c in axis.categories for value in c.values}


@pytest.mark.parametrize("attr", DISPLAYED, ids=lambda a: a.attr_id)
def test_行の鍵は属性の中で重複しない(attr) -> None:
    for axis in attr.display_axes:
        keys = [c.key for c in axis.categories]
        assert len(keys) == len(set(keys)), f"{attr.attr_id}:{axis.key} の行の鍵が重複している"


@pytest.mark.parametrize("attr", DISPLAYED, ids=lambda a: a.attr_id)
def test_同じ値が2つの行に属さない(attr) -> None:
    for axis in attr.display_axes:
        values = [v for c in axis.categories for v in c.values]
        assert len(values) == len(set(values)), f"{attr.attr_id}:{axis.key} で同じ値が2行に属している"


@pytest.mark.parametrize("attr", DISPLAYED, ids=lambda a: a.attr_id)
def test_列挙の行は枠の番号を持ち順序の行は持たない(attr) -> None:
    for axis in attr.display_axes:
        for category in axis.categories:
            if axis.palette == "nominal":
                assert category.color_slot is not None, f"{attr.attr_id}:{category.key} に枠の番号が無い"
            else:
                assert category.color_slot is None, f"{attr.attr_id}:{category.key} は並びが色を決めるので枠を持たない"


def test_枠の番号は全体で重複しない() -> None:
    """**軸をまたいで重複させない。** 位置だけで決めると、1行しか持たない軸どうし
    （トンネルと一方通行）が必ず同じ色になり、別の意味が同じ色で地図に載る。"""
    used: dict[int, str] = {}
    for attr in DISPLAYED:
        for axis in attr.display_axes:
            for category in axis.categories:
                if category.color_slot is None:
                    continue
                where = f"{attr.attr_id}:{axis.key}:{category.key}"
                assert category.color_slot not in used, f"枠{category.color_slot}が{used[category.color_slot]}と{where}で衝突"
                used[category.color_slot] = where
    assert len(used) <= NOMINAL_SLOT_COUNT


@pytest.mark.parametrize("attr", DISPLAYED, ids=lambda a: a.attr_id)
def test_面には表示定義を持たせない(attr) -> None:
    assert attr.geometry in ("line", "point"), f"{attr.attr_id} は面なのに行の定義を持っている"


def test_路面の行は正準分類を過不足なく覆う() -> None:
    canonical = GOOD_OSM_SURFACE_TAGS | BAD_OSM_SURFACE_TAGS
    displayed = _values("surface")
    assert displayed - canonical == set(), "正準分類に無い値が行にある（その行は永久に空になる）"
    assert canonical - displayed == set(), "正準分類のタグが行から漏れている（地図に出ないまま評価に効く）"


def test_停止要因の行は種別を過不足なく覆う() -> None:
    assert _values("stop_poi") == set(STOP_POI_KINDS)


def test_補給の行は種別を過不足なく覆う() -> None:
    assert _values("supply_poi") == set(get_args(SupplyPoiKind))


@pytest.mark.parametrize("attr", DISPLAYED, ids=lambda a: a.attr_id)
def test_地図へ出す属性はタイルの系統を持つ(attr) -> None:
    """持たないと、画面がどのソースから読むかを自分で決めることになる。"""
    assert attr.tile_kind is not None, f"{attr.attr_id} に tile_kind が無い"
