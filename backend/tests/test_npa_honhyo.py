"""`batch/source_adapters/npa_honhyo.py`——警察庁の本票の緯度・経度の列（度分秒を連結した数字列）を10進の度へ読む。

入口は`latitude_from_raw`・`longitude_from_raw`。読めない列と、日本の範囲を外れた値はNoneになる。

ここで見ないもの:
- 生データの列から判定するSQL（自転車の関与・死亡・発生年）と帰属の半径・重み → 実行して数える
  `test_derive_counts.py`・`test_point_tiles.py`
- 本票CSVの取得と保存 → `test_fetch_accident_csv.py`
"""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.batch.source_adapters.npa_honhyo import latitude_from_raw, longitude_from_raw


def encode(degrees: int, minutes: int, milliseconds: int) -> str:
    """本票の表記: 右5桁が秒×1000、次の2桁が分、残りが度（警察庁のコード表の定義）。"""
    return f"{degrees}{minutes:02d}{milliseconds:05d}"


def test_the_digits_read_as_degrees_minutes_and_thousandths_of_a_second():
    assert latitude_from_raw("354010500") == pytest.approx(35 + 40 / 60 + 10.5 / 3600)
    assert longitude_from_raw("1394530250") == pytest.approx(139 + 45 / 60 + 30.25 / 3600)


def test_whitespace_around_the_digits_is_ignored():
    assert latitude_from_raw(" 354010500\n") == latitude_from_raw("354010500")


@pytest.mark.parametrize(
    "raw",
    [
        "",  # 欠損
        "   ",
        "35.40105",  # 数字以外を含む
        "-354010500",
        "abc",
        "1234567",  # 度の桁が無い
    ],
)
def test_a_column_that_is_not_the_notation_has_no_value(raw):
    assert latitude_from_raw(raw) is None
    assert longitude_from_raw(raw) is None


@pytest.mark.parametrize(
    ("raw", "valid"),
    [
        (encode(35, 59, 59999), True),  # 分も秒も60未満
        (encode(35, 60, 0), False),  # 分が60
        (encode(35, 0, 60000), False),  # 秒が60
    ],
)
def test_minutes_or_seconds_of_sixty_or_more_are_broken_values(raw, valid):
    assert (latitude_from_raw(raw) is not None) is valid


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (encode(20, 0, 0), 20.0),  # 範囲の端は含む
        (encode(46, 0, 0), 46.0),
        (encode(19, 59, 59999), None),
        (encode(46, 0, 1), None),
        ("000000000", None),  # 全部0の列
    ],
)
def test_a_latitude_outside_japan_has_no_value(raw, expected):
    assert latitude_from_raw(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (encode(122, 0, 0), 122.0),
        (encode(154, 0, 0), 154.0),
        (encode(121, 59, 59999), None),
        (encode(154, 0, 1), None),
        (encode(35, 0, 0), None),  # 緯度の値を経度の列で読んでも通さない
    ],
)
def test_a_longitude_outside_japan_has_no_value(raw, expected):
    assert longitude_from_raw(raw) == expected


def test_a_real_row_from_the_published_csv_is_read_correctly():
    """本票CSVの実データ1行目（北海道札幌方面）。桁の切り出しの取り違えは、合成した
    値では気づきにくい——秒が3桁ぶんスケールされている点を含め、配布物そのもので確かめる。
    """
    latitude = latitude_from_raw("431007628")
    longitude = longitude_from_raw("1410328320")

    assert latitude is not None and round(latitude, 4) == round(43 + 10 / 60 + 7.628 / 3600, 4)
    assert longitude is not None and round(longitude, 4) == round(141 + 3 / 60 + 28.320 / 3600, 4)


minutes = st.integers(min_value=0, max_value=59)
milliseconds = st.integers(min_value=0, max_value=59999)


@given(degrees=st.integers(min_value=20, max_value=45), minutes=minutes, milliseconds=milliseconds)
def test_any_latitude_in_japan_reads_back_to_the_value_it_was_written_from(degrees, minutes, milliseconds):
    assert latitude_from_raw(encode(degrees, minutes, milliseconds)) == pytest.approx(
        degrees + minutes / 60 + milliseconds / 3_600_000
    )


@given(degrees=st.integers(min_value=122, max_value=153), minutes=minutes, milliseconds=milliseconds)
def test_any_longitude_in_japan_reads_back_to_the_value_it_was_written_from(degrees, minutes, milliseconds):
    assert longitude_from_raw(encode(degrees, minutes, milliseconds)) == pytest.approx(
        degrees + minutes / 60 + milliseconds / 3_600_000
    )
