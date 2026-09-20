"""通行方向の解決（`domain/traffic.py: resolve_direction`）。

タグの生値から「どちら向きに走れるか」を決める判断で、派生バッチ（`derive_way_materials`）
だけが呼ぶ。結果は`way_materials.direction`に入り、探索が逆向きの枝を作ってよいかを決める。
"""

import pytest

from app.domain.traffic import resolve_direction


@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        ({"highway": "residential"}, "both"),
        ({"oneway": "yes"}, "forward"),
        ({"oneway": "-1"}, "backward"),
        # 前後の空白と大文字小文字は正規化する。
        ({"oneway": " YES "}, "forward"),
        # 時間帯で向きが変わる値は両方向として扱う（時刻を持たない列では表せない）。
        ({"oneway": "alternating"}, "both"),
    ],
)
def test_oneway_tag(tags, expected):
    assert resolve_direction(tags) == expected


@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        # 車は一方通行だが自転車は逆走可（contraflow cycling）の代表例。
        ({"oneway": "yes", "oneway:bicycle": "no"}, "both"),
        ({"oneway": "-1", "oneway:bicycle": "yes"}, "forward"),
        ({"oneway": "yes", "oneway:bicycle": "-1"}, "backward"),
        ({"oneway": "yes", "oneway:bicycle": " NO "}, "both"),
        # 解釈できない値のときだけ`oneway`本体へ落ちる。
        ({"oneway": "yes", "oneway:bicycle": "alternating"}, "forward"),
    ],
)
def test_oneway_bicycle_wins_over_oneway(tags, expected):
    assert resolve_direction(tags) == expected


@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        # 環状交差点は構造として一方向にしか通れず、OSMは個々のwayへonewayを付けない慣行が
        # ある。両方向として扱うと、探索が環を逆走する経路を出しうる。
        ({"highway": "tertiary", "junction": "roundabout"}, "forward"),
        ({"highway": "tertiary", "junction": "circular"}, "forward"),
        # OSM側が「両方向」と言っているなら、構造からの推定より優先する。
        ({"highway": "tertiary", "junction": "roundabout", "oneway": "no"}, "both"),
        ({"highway": "tertiary", "junction": "roundabout", "oneway": "-1"}, "backward"),
        # 構造として一方向を含意しない値まで一方通行にしない。
        ({"highway": "tertiary", "junction": "yes"}, "both"),
    ],
)
def test_junction_implies_one_way_only_when_oneway_is_absent(tags, expected):
    assert resolve_direction(tags) == expected
