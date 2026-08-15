"""scripts/measure_tag_coverage.pyの純粋ロジック（集計部分）の検証。

PBF読み取り自体はpyosmium依存かつ実ファイルが要るため、ここでは対象外
（test_import_pbf.pyと同じ切り分け方針）。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from measure_tag_coverage import CoverageCounter, highway_group  # noqa: E402


class TestHighwayGroup:
    def test_arterial_roads_grouped_as_trunk(self):
        assert highway_group("primary") == "幹線"
        assert highway_group("tertiary_link") == "幹線"

    def test_residential_roads_grouped_as_local(self):
        assert highway_group("residential") == "生活道路"
        assert highway_group("living_street") == "生活道路"

    def test_cycle_roads_grouped_separately(self):
        assert highway_group("cycleway") == "自転車専用"
        assert highway_group("track") == "自転車専用"

    def test_unknown_or_missing_highway_is_other(self):
        assert highway_group("service") == "その他"
        assert highway_group(None) == "その他"


class TestCoverageCounter:
    def test_counts_only_tags_of_interest(self):
        counter = CoverageCounter(frozenset({"lanes", "maxspeed"}))
        counter.add("residential", {"highway": "residential", "lanes": "2", "surface": "asphalt"})

        assert counter.total == 1
        assert counter.tag_count["lanes"] == 1
        assert counter.tag_count["maxspeed"] == 0
        # 監視対象外のタグ（surface）は集計されない
        assert "surface" not in counter.tag_count

    def test_blank_value_does_not_count_as_present(self):
        counter = CoverageCounter(frozenset({"lanes"}))
        counter.add("residential", {"highway": "residential", "lanes": "  "})

        assert counter.tag_count["lanes"] == 0

    def test_breaks_down_by_highway_group(self):
        counter = CoverageCounter(frozenset({"maxspeed"}))
        counter.add("primary", {"highway": "primary", "maxspeed": "50"})
        counter.add("residential", {"highway": "residential"})

        assert counter.total_by_group["幹線"] == 1
        assert counter.total_by_group["生活道路"] == 1
        assert counter.tag_count_by_group[("maxspeed", "幹線")] == 1
        assert counter.tag_count_by_group[("maxspeed", "生活道路")] == 0

    def test_report_lines_include_total_and_header(self):
        counter = CoverageCounter(frozenset({"lanes"}))
        counter.add("residential", {"highway": "residential", "lanes": "1"})

        lines = counter.report_lines()

        assert lines[0].startswith("対象way数: 1件")
        assert any("lanes" in line for line in lines)
