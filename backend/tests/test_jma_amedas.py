"""`domain/jma_amedas.py`——アメダス観測値の読み替えと体感温度。

観測値の取得・キャッシュは`test_jma_amedas_service.py`が持つ。
"""

import math

import pytest

from app.domain.jma_amedas import (
    apparent_temperature_from_amedas,
    wind_direction_degrees_from_jma_code,
    wind_direction_label_from_jma_code,
)


class TestWindDirectionFromJmaCode:
    """**JMAの割当は独特**——0が静穏で、1が北北東、そこから22.5度ずつ時計回りに進み、
    16で北（一周）へ戻る。0起点の一般的な16方位表をそのまま当てると全方位がずれる。
    """

    def test_code_one_is_north_north_east(self):
        assert wind_direction_label_from_jma_code(1) == "北北東"
        assert wind_direction_degrees_from_jma_code(1) == 22.5

    def test_the_last_code_wraps_back_to_north(self):
        """16は360度ではなく0度（北）。360のまま配ると、方位の比較が0と360で割れる。"""
        assert wind_direction_label_from_jma_code(16) == "北"
        assert wind_direction_degrees_from_jma_code(16) == 0.0

    def test_calm_has_no_direction(self):
        """0は静穏（風速がほぼ0で方位不定）。北として配ると、無風の地点に矢印が出る。"""
        assert wind_direction_label_from_jma_code(0) is None
        assert wind_direction_degrees_from_jma_code(0) is None

    def test_a_missing_reading_has_no_direction(self):
        assert wind_direction_label_from_jma_code(None) is None
        assert wind_direction_degrees_from_jma_code(None) is None

    def test_every_code_maps_to_a_distinct_direction(self):
        labels = [wind_direction_label_from_jma_code(code) for code in range(1, 17)]
        degrees = [wind_direction_degrees_from_jma_code(code) for code in range(1, 17)]

        assert len(set(labels)) == 16
        assert len(set(degrees)) == 16

    def test_the_label_and_the_angle_agree(self):
        """ラベルと角度は別々に引く。片方だけ直すと、矢印の向きと文字が食い違う。"""
        for code in range(1, 17):
            expected = ["北", "北北東", "北東", "東北東", "東", "東南東", "南東", "南南東",
                        "南", "南南西", "南西", "西南西", "西", "西北西", "北西", "北北西"]
            index = int(wind_direction_degrees_from_jma_code(code) / 22.5)

            assert wind_direction_label_from_jma_code(code) == expected[index]


class TestApparentTemperature:
    """JMAは体感温度を配らないため、豪州気象局の式で自前計算する。"""

    def test_it_reproduces_the_published_formula(self):
        temperature, humidity, wind = 30.0, 70.0, 2.0
        vapour = (humidity / 100) * 6.105 * math.exp(17.27 * temperature / (237.7 + temperature))
        expected = temperature + 0.33 * vapour - 0.70 * wind - 4.00

        assert apparent_temperature_from_amedas(temperature, humidity, wind) == pytest.approx(expected)

    def test_humid_heat_feels_hotter_than_the_air_temperature(self):
        """蒸し暑い日（26.5℃・湿度70%・風速3.5m/s）は、湿度のぶん体感が気温を上回る。
        符号や係数を取り違えると、ここで下回る。
        """
        assert apparent_temperature_from_amedas(26.5, 70.0, 3.5) > 26.5

    def test_humidity_makes_it_feel_hotter(self):
        dry = apparent_temperature_from_amedas(30.0, 30.0, 2.0)
        humid = apparent_temperature_from_amedas(30.0, 90.0, 2.0)

        assert humid > dry

    def test_wind_makes_it_feel_cooler(self):
        still = apparent_temperature_from_amedas(30.0, 70.0, 0.0)
        breezy = apparent_temperature_from_amedas(30.0, 70.0, 5.0)

        assert breezy < still

    @pytest.mark.parametrize(
        ("temperature", "humidity", "wind"),
        [(None, 70.0, 2.0), (30.0, None, 2.0), (30.0, 70.0, None)],
    )
    def test_a_missing_input_gives_no_value(self, temperature, humidity, wind):
        """センサー未搭載・欠測。欠けた入力を0で埋めると、無風・乾燥として計算され
        実際よりかなり低い体感温度が出る。
        """
        assert apparent_temperature_from_amedas(temperature, humidity, wind) is None
