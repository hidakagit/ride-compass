"""`domain/address_area.py`——住所の表記の揃え方（`standardize_address`）と表示名の組み立て方（`address_full_name`）。

打った入力と区画の鍵の両方に同じ揃え方をかけるので、書き方の違う同じ住所が同じ文字列になることを見る。

ここで見ないもの:
- 区画の名前から作る鍵の別形（書き始める段・郡を省いた形・字の有無）→ `test_address_areas.py`（派生の段を通して見る）
- 郡を持たない区画の表示名 → `test_place_search_route.py`（検索の候補の名前）
"""

import pytest

from app.domain.address_area import AddressAreaName, address_full_name, standardize_address


@pytest.mark.parametrize(("typed", "listed"), [
    # ハイフンと長音の類
    ("西新宿2ー8ー1", "西新宿2-8-1"),
    ("西新宿2－8－1", "西新宿2-8-1"),
    ("西新宿2‐8―1", "西新宿2-8-1"),
    ("西新宿2ｰ8−1", "西新宿2-8-1"),
    # 漢数字（「十」を含む）
    ("西新宿二丁目", "西新宿2丁目"),
    ("本町十二丁目", "本町12丁目"),
    ("本町二十三", "本町23"),
    # 数字の後の「丁目」「丁」は区切り
    ("西新宿2丁目8", "西新宿2-8"),
    ("本町3丁", "本町3-"),
    # 「大字」は書いても書かなくてもよい
    ("大字奈良井", "奈良井"),
    # 「ヶ」「ヵ」「ケ」「が」
    ("市ヶ谷", "市ケ谷"),
    ("自由が丘", "自由ヶ丘"),
    ("霞ヵ関", "霞が関"),
    # 「の」「之」「ノ」
    ("北の丸公園", "北ノ丸公園"),
    ("寺之上", "寺の上"),
    # 全角・半角・大文字・空白
    ("東京都　新宿区 西新宿", "東京都新宿区西新宿"),
    ("ＡＢＣ町", "abc町"),
], ids=lambda value: value)
def test_書き方の違う同じ住所は同じ形に揃う(typed, listed):
    assert standardize_address(typed) == standardize_address(listed)


def test_揃えた形は丁目を区切りにし番地をそのまま続ける():
    """丁目の鍵（「西新宿2-」）を頭に持つ形になり、番地まで打った入力でも丁目までの鍵が頭に当たる。"""
    assert standardize_address("東京都 新宿区 西新宿二丁目八番一号") == "東京都新宿区西新宿2-8番1号"


def test_表示名は郡の町村に郡の名前を付ける():
    chain = [AddressAreaName("東京都", None), AddressAreaName("日の出町", "西多摩郡"), AddressAreaName("大字平井", None)]

    assert address_full_name(chain) == "東京都西多摩郡日の出町大字平井"
