"""`domain/jma_area.py`——区域（class20）のコードから、気象庁の警報エリアを解決する。

地点から区域のコードを引く側は`test_jma_area_boundaries.py`、area.jsonを地域マスタへ解く側は
`test_jma_warning_client.py`、解決した先のエリアから警報を取り出す側は`test_jma_warning_domain.py`が持つ。
"""

from app.domain.jma_area import AreaEntry, AreaMaster, ResolvedArea, resolve_area

OFFICE = "130000"


def _master(
    class20s: dict[str, AreaEntry] | None = None,
    class15s: dict[str, AreaEntry] | None = None,
    class10s: dict[str, AreaEntry] | None = None,
) -> AreaMaster:
    return AreaMaster(class20s=class20s or {}, class15s=class15s or {}, class10s=class10s or {})


def _entry(parent: str | None = None, name: str | None = None) -> AreaEntry:
    return AreaEntry(parent=parent, name=name)


class TestResolveArea:
    def test_it_walks_up_to_the_subdivision_and_its_office(self):
        resolved = resolve_area(
            "1310100",
            _master(
                class20s={"1310100": _entry("131001")},
                class15s={"131001": _entry("130010")},
                class10s={"130010": _entry(OFFICE, "東京地方")},
            ),
        )

        assert resolved == ResolvedArea(
            class20_code="1310100", class10_code="130010", office_code=OFFICE, class10_name="東京地方"
        )

    def test_an_area_whose_parent_is_already_a_subdivision_resolves_in_one_step(self):
        """class15を必ず1段挟む前提で書くと、そこだけ解決できない。"""
        resolved = resolve_area(
            "0120200",
            _master(class20s={"0120200": _entry("016010")}, class10s={"016010": _entry("016000", "石狩地方")}),
        )

        assert resolved is not None
        assert resolved.class10_code == "016010"

    def test_it_keeps_climbing_while_the_parent_is_still_an_intermediate(self):
        resolved = resolve_area(
            "1310100",
            _master(
                class20s={"1310100": _entry("a")},
                class15s={"a": _entry("b"), "b": _entry("c")},
                class10s={"c": _entry(OFFICE, "地方")},
            ),
        )

        assert resolved is not None
        assert resolved.class10_code == "c"

    def test_an_area_the_master_does_not_list_is_none(self):
        """既定のエリアへ倒すと、無関係な地域の警報が出る。"""
        assert resolve_area("9999900", _master(class20s={"1310100": _entry("x")})) is None

    def test_an_area_without_a_parent_is_none(self):
        assert resolve_area("1310100", _master(class20s={"1310100": _entry()})) is None

    def test_a_chain_that_breaks_before_a_subdivision_is_none(self):
        assert resolve_area("1310100", _master(class20s={"1310100": _entry("missing")})) is None

    def test_an_intermediate_without_a_parent_is_none(self):
        resolved = resolve_area("1310100", _master(class20s={"1310100": _entry("a")}, class15s={"a": _entry()}))

        assert resolved is None

    def test_a_cycle_in_the_master_is_none_instead_of_hanging(self):
        resolved = resolve_area(
            "1310100",
            _master(class20s={"1310100": _entry("a")}, class15s={"a": _entry("b"), "b": _entry("a")}),
        )

        assert resolved is None

    def test_a_subdivision_without_an_office_is_none(self):
        """府県予報区が分からなければ、そもそも問い合わせ先が決まらない。"""
        resolved = resolve_area(
            "1310100",
            _master(class20s={"1310100": _entry("130010")}, class10s={"130010": _entry(name="東京地方")}),
        )

        assert resolved is None

    def test_a_subdivision_without_a_name_is_none(self):
        """名前は利用者へ「どの区域の警報か」を示すために要る。空で出さない。"""
        resolved = resolve_area(
            "1310100",
            _master(class20s={"1310100": _entry("130010")}, class10s={"130010": _entry(OFFICE)}),
        )

        assert resolved is None
