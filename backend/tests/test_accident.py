"""`domain/accident.py`——警察庁の交通事故統計を取り込むための純関数。

生データの列から何を判定するかのSQL断片もここが持つが、**その文字列は書き写さない**
（判定が実際にどう当たるかはDBへ通すテストの責務）。
"""

from app.domain.accident import (
    BICYCLE_PARTY_TYPE_CODES,
    latitude_from_raw,
    longitude_from_raw,
)

# 東京駅付近。本票は度分秒を1つの数値へ連結して持つ（右5桁=秒×1000、次の2桁=分、残り=度）。
TOKYO_LATITUDE_RAW = "354052000"  # 35度40分52.000秒
TOKYO_LONGITUDE_RAW = "1394557000"  # 139度45分57.000秒


class TestCoordinatesFromRawDms:
    """度分秒の連結表記を10進の度へ直す。**根拠のない推測はしない**——読めない値は
    Noneで返し、0度や既定の地点へ倒さない。"""

    def test_it_reads_degrees_minutes_and_seconds(self):
        assert latitude_from_raw(TOKYO_LATITUDE_RAW) == 35 + 40 / 60 + 52 / 3600
        assert longitude_from_raw(TOKYO_LONGITUDE_RAW) == 139 + 45 / 60 + 57 / 3600

    def test_a_real_row_from_the_published_csv_is_read_correctly(self):
        """本票CSVの実データ1行目（北海道札幌方面）。桁の切り出しの取り違えは、合成した
        値では気づきにくい——秒が3桁ぶんスケールされている点を含め、配布物そのもので確かめる。
        """
        latitude = latitude_from_raw("431007628")
        longitude = longitude_from_raw("1410328320")

        assert latitude is not None and round(latitude, 4) == round(43 + 10 / 60 + 7.628 / 3600, 4)
        assert longitude is not None and round(longitude, 4) == round(141 + 3 / 60 + 28.320 / 3600, 4)

    def test_an_all_zero_value_is_none(self):
        """欠損はゼロ埋めで入ってくる。0度0分0秒として通すと、ギニア湾に事故点が並ぶ。"""
        assert latitude_from_raw("000000000") is None
        assert longitude_from_raw("0000000000") is None

    def test_surrounding_spaces_are_ignored(self):
        assert latitude_from_raw(f"  {TOKYO_LATITUDE_RAW} ") == latitude_from_raw(TOKYO_LATITUDE_RAW)

    def test_an_empty_or_non_numeric_value_is_none(self):
        assert latitude_from_raw("") is None
        assert latitude_from_raw("   ") is None
        assert latitude_from_raw("35.4052") is None
        assert latitude_from_raw("abcdefghi") is None

    def test_a_value_too_short_to_hold_degrees_is_none(self):
        """右7桁は分と秒で埋まる。それ以下だと度の桁が無く、分秒だけを度と読んでしまう。"""
        assert latitude_from_raw("3540520") is None

    def test_minutes_or_seconds_out_of_range_are_none(self):
        """60以上の分・秒は壊れた値。そのまま足すと隣の度へはみ出す。"""
        assert latitude_from_raw("356052000") is None
        assert latitude_from_raw("354060000") is None

    def test_a_result_outside_japan_is_none(self):
        """度分秒の切り出しがずれると、桁の並びは正しいまま値だけが大きく外れる。
        範囲の検査はその取り違えを捕まえるためのもので、対象地域の絞り込みではない。
        """
        assert latitude_from_raw("104052000") is None  # 10度台
        assert longitude_from_raw("0994557000") is None  # 99度台

    def test_the_two_readings_apply_their_own_range(self):
        """緯度として妥当な値が経度としては妥当でない、という組み合わせがある。
        片方の範囲で両方を見ると、取り違えを見逃す。
        """
        assert latitude_from_raw(TOKYO_LATITUDE_RAW) is not None
        assert longitude_from_raw(TOKYO_LATITUDE_RAW) is None


def test_only_bicycles_count_as_bicycle_parties():
    """当事者種別のうち自転車は51（自転車）と52（電動アシスト）。
    **59（軽車両－その他）は入れない**——手押し車等が自転車事故として数えられる。
    """
    assert BICYCLE_PARTY_TYPE_CODES == frozenset({"51", "52"})
    assert "59" not in BICYCLE_PARTY_TYPE_CODES
