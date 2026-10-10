"""`domain/stop_place.py`——打った語を立ち寄り先の群の名前として読む判断。

ここで見ないもの:
- 群の名前で引いた店の並び（名前に当たる店との前後・近い順） → `test_place_search_route.py`
- 群へ入れる地点 → `test_stop_places.py`
"""

import pytest

from app.domain.stop_place import StopPlaceGroup, queried_group


@pytest.mark.parametrize(("query", "group"), [
    pytest.param("コンビニ", StopPlaceGroup.CONVENIENCE, id="群の名前"),
    pytest.param("こんびに", StopPlaceGroup.CONVENIENCE, id="ひらがな"),
    pytest.param("ｺﾝﾋﾞﾆ", StopPlaceGroup.CONVENIENCE, id="半角のかな"),
    pytest.param(" Convenience Store ", StopPlaceGroup.CONVENIENCE, id="大文字と空白"),
    pytest.param("スーパー銭湯", StopPlaceGroup.BATH, id="長音を残す"),
    # 群の名前を含むだけの語は、店の名前（「大江戸温泉物語」）でありうる。
    pytest.param("コンビニ王子", None, id="群の名前を含むだけ"),
    pytest.param("一蘭", None, id="群の名前でない"),
])
def test_a_query_is_read_as_a_group_only_when_it_is_a_name_of_the_group(query, group):
    assert queried_group(query) == group
