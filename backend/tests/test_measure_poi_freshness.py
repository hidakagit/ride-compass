"""scripts/measure_poi_freshness.pyの純粋ロジック（タグ判定・鮮度バケット化・集計）の検証。

PBF読み取り自体はpyosmium依存かつ実ファイルが要るため、ここでは対象外
（test_measure_tag_coverage.pyと同じ切り分け方針）。
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from measure_poi_freshness import FreshnessCounter, age_bucket, node_matches  # noqa: E402


class TestNodeMatches:
    def test_matches_convenience_shop(self):
        assert node_matches({"shop": "convenience"}) == ("shop", "convenience")

    def test_matches_vending_machine(self):
        assert node_matches({"amenity": "vending_machine"}) == ("amenity", "vending_machine")

    def test_no_match_returns_none(self):
        assert node_matches({"shop": "supermarket"}) is None
        assert node_matches({}) is None


class TestAgeBucket:
    def test_under_one_year(self):
        assert age_bucket(0.5) == "1年未満"

    def test_one_to_two_years(self):
        assert age_bucket(1.5) == "1-2年"

    def test_two_to_three_years(self):
        assert age_bucket(2.9) == "2-3年"

    def test_three_to_five_years(self):
        assert age_bucket(4.0) == "3-5年"

    def test_five_years_and_over(self):
        assert age_bucket(5.0) == "5年以上"
        assert age_bucket(20.0) == "5年以上"

    def test_boundary_is_exclusive_on_lower_bucket(self):
        # ちょうど1.0年は「1年未満」ではなく「1-2年」側に入る（years < boundで判定するため）。
        assert age_bucket(1.0) == "1-2年"


class TestFreshnessCounter:
    def test_counts_check_date_presence(self):
        counter = FreshnessCounter()
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        counter.add(("shop", "convenience"), {"check_date": "2025-06-01"}, datetime(2020, 1, 1, tzinfo=timezone.utc), now)
        counter.add(("shop", "convenience"), {}, datetime(2020, 1, 1, tzinfo=timezone.utc), now)
        assert counter.total_by_tag[("shop", "convenience")] == 2
        assert counter.checked_by_tag[("shop", "convenience")] == 1

    def test_survey_date_also_counts_as_checked(self):
        counter = FreshnessCounter()
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        counter.add(("amenity", "toilets"), {"survey:date": "2024-01-01"}, datetime(2020, 1, 1, tzinfo=timezone.utc), now)
        assert counter.checked_by_tag[("amenity", "toilets")] == 1

    def test_buckets_by_edit_age(self):
        counter = FreshnessCounter()
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        counter.add(("amenity", "vending_machine"), {}, datetime(2025, 12, 1, tzinfo=timezone.utc), now)  # ~1ヶ月前
        counter.add(("amenity", "vending_machine"), {}, datetime(2015, 1, 1, tzinfo=timezone.utc), now)  # ~11年前
        tag = ("amenity", "vending_machine")
        assert counter.age_bucket_by_tag[(tag, "1年未満")] == 1
        assert counter.age_bucket_by_tag[(tag, "5年以上")] == 1

    def test_report_lines_empty_when_no_data(self):
        counter = FreshnessCounter()
        lines = counter.report_lines()
        assert any("見つかりませんでした" in line for line in lines)
