"""scripts/measure_way_segment_split.pyの純粋ロジック（レポート整形）の検証。

DB接続を伴う集計クエリ本体（measure関数）はPostGIS実データが要るため対象外
（test_measure_tag_coverage.pyと同じ切り分け方針）。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from measure_way_segment_split import report_lines  # noqa: E402

_SAMPLE_ROW = {
    "way_count": 100,
    "total_segments_model_a": 350,
    "avg_segments_per_way_a": 3.5,
    "cost_multiplier_a": 3.5,
    "total_segments_model_b": 220,
    "avg_segments_per_way_b": 2.2,
    "cost_multiplier_b": 2.2,
    "ways_where_b_undersplits": 60,
    "avg_segment_diff_a_minus_b": 1.3,
    "p50_a": 3,
    "p90_a": 7,
    "p99_a": 12,
    "max_segments_single_way_a": 15,
}


class TestReportLines:
    def test_includes_way_count_and_both_model_multipliers(self):
        lines = report_lines(_SAMPLE_ROW)
        text = "\n".join(lines)

        assert "対象way数: 100件" in text
        assert "3.5倍" in text
        assert "2.2倍" in text

    def test_includes_divergence_between_models(self):
        lines = report_lines(_SAMPLE_ROW)
        text = "\n".join(lines)

        assert "60" in text
        assert "1.3" in text
