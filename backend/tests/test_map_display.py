"""地図の最上位の束ね方が、それ自身で閉じていること。

**母集団は導出する**（設計原則 構造仕様12）——種別すべて・グループすべてに対して回す。
所属先の無い種別があると、そのレイヤーはどのグループにも出ず、画面からは
「チップが無い」としか見えない（例外にならない）。
"""

from app.domain.map_display import (
    MAP_LAYER_CATEGORIES,
    MAP_OVERLAY_GROUPS,
    WEATHER_ELEMENTS,
    weather_element_path_group,
    weather_element_tile,
)


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


def test_気象の要素はチップ_名前付きソース_描き方の組で一意() -> None:
    """同じ組が2件あると、画面では同じソース・レイヤーへ畳まれて片方が黙って消える。"""
    keys = [(element.group, element.source, element.kind) for element in WEATHER_ELEMENTS]
    assert len(keys) == len(set(keys))


def test_タイルで描く気象の要素は配信元の仕様を持つ() -> None:
    """仕様が無いと画面はズーム範囲を知らずにソースを作ることになる。"""
    for element in WEATHER_ELEMENTS:
        if element.kind not in ("rasterTile", "vectorTile"):
            continue
        tile = weather_element_tile(element)
        assert tile is not None, f"{element.group}/{element.source}"
        if element.kind == "vectorTile":
            assert tile.vector_layer is not None, f"{element.group}/{element.source} のベクタのレイヤー名が無い"


def test_配信元から取る気象の要素はパスの系統を持つ() -> None:
    """系統が無いと、画面のデータ層は配信元のURLを組み立てられない。"""
    for element in WEATHER_ELEMENTS:
        if element.jma_element is None:
            continue
        assert weather_element_path_group(element) is not None, f"{element.group}/{element.source}"


def test_配信元から取る気象の要素はチップと名前付きソースで一意() -> None:
    """画面のデータ層は（チップ, 名前付きソース）から配信要素idを引く。2件あるとどちらを取るか決まらない。"""
    keys = [(element.group, element.source) for element in WEATHER_ELEMENTS if element.jma_element is not None]
    assert len(keys) == len(set(keys))
