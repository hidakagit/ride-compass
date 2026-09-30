"""`domain/weather_elements.py: stage_first_frames`——時刻の段を1本の時系列へつないだときに各段が最初に描くコマ。

時刻は"HHMM"で書く（つなぎ方は時刻の文字列の大小だけを見る）。
"""

from app.domain.jma_tile_specs import JmaFrame
from app.domain.weather_elements import stage_first_frames


def _frames(*validtimes: str) -> list[JmaFrame]:
    return [JmaFrame(validtime, "none", validtime) for validtime in validtimes]


def test_each_stage_continues_after_the_last_frame_of_the_stages_before():
    stages = [_frames("0900", "1000"), _frames("1000", "1100"), _frames("0930", "1200")]

    assert [frame and frame.validtime for frame in stage_first_frames(stages)] == ["0900", "1100", "1200"]


def test_a_stage_covered_by_the_stages_before_draws_nothing():
    stages = [_frames("0900", "1000"), _frames("0930")]

    assert [frame and frame.validtime for frame in stage_first_frames(stages)] == ["0900", None]


def test_after_an_empty_stage_the_next_continues_from_the_stage_before_it():
    stages = [_frames("0900"), [], _frames("0900", "1000")]

    assert [frame and frame.validtime for frame in stage_first_frames(stages)] == ["0900", None, "1000"]


def test_no_frames_in_any_stage():
    assert stage_first_frames([[], []]) == [None, None]
