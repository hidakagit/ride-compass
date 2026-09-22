"""地図の最上位の束ね方が、それ自身で閉じていること。

**母集団は導出する**（設計原則 構造仕様12）——種別すべて・グループすべてに対して回す。
所属先の無い種別があると、そのレイヤーはどのグループにも出ず、画面からは
「チップが無い」としか見えない（例外にならない）。
"""

from app.domain.map_display import MAP_LAYER_CATEGORIES, MAP_OVERLAY_GROUPS


def test_グループの鍵は重複しない() -> None:
    keys = [group.key for group in MAP_OVERLAY_GROUPS]
    assert len(keys) == len(set(keys))


def test_種別の鍵は重複しない() -> None:
    keys = [category.key for category in MAP_LAYER_CATEGORIES]
    assert len(keys) == len(set(keys))


def test_すべての種別が実在するグループへ属する() -> None:
    groups = {group.key for group in MAP_OVERLAY_GROUPS}
    for category in MAP_LAYER_CATEGORIES:
        assert category.group in groups, f"{category.key} の所属先 {category.group} が無い"


def test_すべてのグループに属する種別がある() -> None:
    """空のグループは、見出しだけが出て中身が無いチップ列になる。"""
    used = {category.group for category in MAP_LAYER_CATEGORIES}
    for group in MAP_OVERLAY_GROUPS:
        assert group.key in used, f"{group.key} に属する種別が無い"
