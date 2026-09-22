"""`domain/jma_area.py`——市区町村コードから、気象庁の警報エリアを解決する。

市区町村コードの取得は`test_jma_warning_client.py`、解決した先のエリアから警報を
取り出す側は`test_jma_warning_domain.py`が持つ。
"""

from app.domain.jma_area import ResolvedArea, municipality_code_to_class20_code, resolve_area

OFFICE = "130000"


def _area_data(
    class20s: dict | None = None, class15s: dict | None = None, class10s: dict | None = None
) -> dict:
    return {
        "class20s": class20s if class20s is not None else {},
        "class15s": class15s if class15s is not None else {},
        "class10s": class10s if class10s is not None else {},
    }


def test_the_class20_code_is_the_municipality_code_with_two_zeros():
    assert municipality_code_to_class20_code("13101") == "1310100"


class TestResolveArea:
    def test_it_walks_up_to_the_subdivision_and_its_office(self):
        resolved = resolve_area(
            "13101",
            _area_data(
                class20s={"1310100": {"parent": "131001"}},
                class15s={"131001": {"parent": "130010"}},
                class10s={"130010": {"parent": OFFICE, "name": "東京地方"}},
            ),
        )

        assert resolved == ResolvedArea(
            class20_code="1310100", class10_code="130010", office_code=OFFICE, class10_name="東京地方"
        )

    def test_a_municipality_whose_parent_is_already_a_subdivision_resolves_in_one_step(self):
        """class15を必ず1段挟む前提で書くと、そこだけ解決できない。"""
        resolved = resolve_area(
            "01202",
            _area_data(
                class20s={"0120200": {"parent": "016010"}},
                class10s={"016010": {"parent": "016000", "name": "石狩地方"}},
            ),
        )

        assert resolved is not None
        assert resolved.class10_code == "016010"

    def test_it_keeps_climbing_while_the_parent_is_still_an_intermediate(self):
        resolved = resolve_area(
            "13101",
            _area_data(
                class20s={"1310100": {"parent": "a"}},
                class15s={"a": {"parent": "b"}, "b": {"parent": "c"}},
                class10s={"c": {"parent": OFFICE, "name": "地方"}},
            ),
        )

        assert resolved is not None
        assert resolved.class10_code == "c"

    def test_a_municipality_the_master_does_not_list_is_none(self):
        """既定のエリアへ倒すと、無関係な地域の警報が出る。"""
        assert resolve_area("99999", _area_data(class20s={"1310100": {"parent": "x"}})) is None

    def test_a_municipality_without_a_parent_is_none(self):
        assert resolve_area("13101", _area_data(class20s={"1310100": {}})) is None

    def test_a_chain_that_breaks_before_a_subdivision_is_none(self):
        resolved = resolve_area(
            "13101", _area_data(class20s={"1310100": {"parent": "missing"}}, class15s={})
        )

        assert resolved is None

    def test_an_intermediate_without_a_parent_is_none(self):
        resolved = resolve_area(
            "13101", _area_data(class20s={"1310100": {"parent": "a"}}, class15s={"a": {}})
        )

        assert resolved is None

    def test_a_cycle_in_the_master_is_none_instead_of_hanging(self):
        resolved = resolve_area(
            "13101",
            _area_data(
                class20s={"1310100": {"parent": "a"}},
                class15s={"a": {"parent": "b"}, "b": {"parent": "a"}},
            ),
        )

        assert resolved is None

    def test_a_subdivision_without_an_office_is_none(self):
        """府県予報区が分からなければ、そもそも問い合わせ先が決まらない。"""
        resolved = resolve_area(
            "13101",
            _area_data(
                class20s={"1310100": {"parent": "130010"}},
                class10s={"130010": {"name": "東京地方"}},
            ),
        )

        assert resolved is None

    def test_a_subdivision_without_a_name_is_none(self):
        """名前は利用者へ「どの区域の警報か」を示すために要る。空で出さない。"""
        resolved = resolve_area(
            "13101",
            _area_data(
                class20s={"1310100": {"parent": "130010"}},
                class10s={"130010": {"parent": OFFICE}},
            ),
        )

        assert resolved is None

    def test_a_master_missing_whole_sections_is_none(self):
        assert resolve_area("13101", {}) is None
