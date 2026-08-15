import csv

import pytest

from app.batch.import_accidents import _REQUIRED_COLUMNS, iter_kanto_rows, parse_years

# honhyo_2023.csv実データ（2026-08-16取得）の列数・列位置に合わせたテスト行を作る。
# COL_PREFECTURE_CODE=1, COL_POLICE_STATION_CODE=2, COL_HONHYO_NUMBER=3, COL_DEATH_COUNT=5,
# COL_PARTY_TYPE_A=38, COL_PARTY_TYPE_B=39, COL_LATITUDE=60, COL_LONGITUDE=61 (0始まり)。


def _make_row(
    prefecture_code="30",
    police_station_code="101",
    honhyo_number="0001",
    death_count="000",
    party_type_a="01",
    party_type_b="51",
    latitude="353923456",
    longitude="1394123456",
) -> list[str]:
    row = ["0"] * _REQUIRED_COLUMNS
    row[1] = prefecture_code
    row[2] = police_station_code
    row[3] = honhyo_number
    row[5] = death_count
    row[38] = party_type_a
    row[39] = party_type_b
    row[60] = latitude
    row[61] = longitude
    return row


def _write_csv(path, rows: list[list[str]]) -> None:
    with open(path, "w", encoding="cp932", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["header"] * _REQUIRED_COLUMNS)
        writer.writerows(rows)


class TestParseYears:
    def test_range(self):
        assert parse_years("2019-2021") == [2019, 2020, 2021]

    def test_individual(self):
        assert parse_years("2019,2021") == [2019, 2021]

    def test_mixed(self):
        assert parse_years("2019-2020,2023") == [2019, 2020, 2023]

    def test_single_year(self):
        assert parse_years("2024") == [2024]


class TestIterKantoRows:
    def test_keeps_kanto_row(self, tmp_path):
        path = tmp_path / "honhyo_2023.csv"
        _write_csv(path, [_make_row(prefecture_code="30")])  # 30=東京

        records = list(iter_kanto_rows(path, 2023))

        assert len(records) == 1
        accident_id, year, fatal, bicycle, lon, lat = records[0]
        assert accident_id == "2023-30-101-0001"
        assert year == 2023
        assert fatal is False
        assert bicycle is True  # party_type_b=51(自転車)
        assert lat is not None and lon is not None

    def test_drops_non_kanto_row(self, tmp_path):
        path = tmp_path / "honhyo_2023.csv"
        _write_csv(path, [_make_row(prefecture_code="10")])  # 10=北海道

        assert list(iter_kanto_rows(path, 2023)) == []

    def test_skips_row_with_too_few_columns(self, tmp_path):
        path = tmp_path / "honhyo_2023.csv"
        with open(path, "w", encoding="cp932", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["header"] * _REQUIRED_COLUMNS)
            writer.writerow(["30", "101"])  # 列数不足

        assert list(iter_kanto_rows(path, 2023)) == []

    def test_skips_row_with_unparseable_coordinates(self, tmp_path):
        path = tmp_path / "honhyo_2023.csv"
        _write_csv(path, [_make_row(prefecture_code="30", latitude="000000000", longitude="0000000000")])

        assert list(iter_kanto_rows(path, 2023)) == []

    def test_raises_when_header_column_count_differs(self, tmp_path):
        # 2026-08-16実データ確認: 2019〜2021年のCSVは58列（2022年以降は68列）という
        # 別スキーマだった。個々の行を静かにスキップするのではなく、その年の取込全体を
        # 明示的に失敗させて気づける形にする。
        path = tmp_path / "honhyo_2019.csv"
        with open(path, "w", encoding="cp932", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["header"] * 58)
            writer.writerow(["30"] * 58)

        with pytest.raises(ValueError, match="想定と異なる列数"):
            list(iter_kanto_rows(path, 2019))

    def test_fatal_and_non_bicycle_row(self, tmp_path):
        path = tmp_path / "honhyo_2023.csv"
        _write_csv(
            path,
            [_make_row(prefecture_code="45", death_count="001", party_type_a="03", party_type_b="76")],
        )

        records = list(iter_kanto_rows(path, 2023))

        assert len(records) == 1
        _, _, fatal, bicycle, _, _ = records[0]
        assert fatal is True
        assert bicycle is False
