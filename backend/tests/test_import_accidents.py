import csv

import asyncpg
import httpx
import pytest
import pytest_asyncio

from app.batch import import_accidents
from app.batch._common import asyncpg_dsn
from app.batch.import_accidents import _REQUIRED_COLUMNS, iter_kanto_rows, parse_years, run_import
from tests.conftest import TEST_DATABASE_URL

# xdist_group="postgis": accident_connは同じridecompass_test DBのaccident_points/
# accident_import_runsテーブルを無条件DELETEで初期化する。他のpostgis系テストと別workerで
# 並走すると互いのDELETEで相手のseed行が消えるflaky失敗を起こすため固定する
# （docs/testing.md、test_import_designations.pyのdesignation_connと同じ理由）。
pytestmark = [pytest.mark.xdist_group(name="postgis"), pytest.mark.postgis]

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


@pytest_asyncio.fixture
async def accident_conn():
    try:
        conn = await asyncpg.connect(asyncpg_dsn(TEST_DATABASE_URL))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"ridecompass_test DBに接続できないためスキップ: {exc}")
    try:
        await conn.execute("DELETE FROM accident_points")
        await conn.execute("DELETE FROM accident_import_runs")
        yield conn
    finally:
        await conn.execute("DELETE FROM accident_points")
        await conn.execute("DELETE FROM accident_import_runs")
        await conn.close()


class TestRunImportOrchestration:
    """run_import本体（ダウンロード→ステージング→MERGE→run記録）の結合検証（改善計画T331）。

    run_importのオーケストレーション本体（メイン処理フロー）はこれまでCI未検証で
    手動E2Eスクリプトでしか確認されていなかった（scripts/verify_phase1_e2e.py相当）。

    実HTTPは行わない。download_to_path（app/batch/_common.py）は「dest（DATA_DIR配下）が
    既に存在すればHTTPを省略する」設計のため、DATA_DIRをtmp_pathへ差し替えてCSVを
    事前配置することで、実ネットワーク・実ファイルダウンロード無しにrun_import全体
    （DB書き込み・run記録・冪等UPSERT・失敗時のstatus更新）を検証する。
    """

    async def test_writes_accident_points_and_marks_run_succeeded(self, accident_conn, tmp_path, monkeypatch):
        monkeypatch.setattr(import_accidents, "DATA_DIR", tmp_path)
        _write_csv(
            tmp_path / "honhyo_2023.csv",
            [
                _make_row(prefecture_code="30", honhyo_number="0001", death_count="000", party_type_b="51"),
                _make_row(
                    prefecture_code="45",
                    honhyo_number="0002",
                    death_count="001",
                    party_type_a="03",
                    party_type_b="76",
                ),
            ],
        )

        result = await run_import([2023], TEST_DATABASE_URL, dry_run=False)

        assert result == 0
        points = await accident_conn.fetch(
            "SELECT accident_id, occurred_year, fatal, involves_bicycle FROM accident_points ORDER BY accident_id"
        )
        assert [dict(r) for r in points] == [
            {"accident_id": "2023-30-101-0001", "occurred_year": 2023, "fatal": False, "involves_bicycle": True},
            {"accident_id": "2023-45-101-0002", "occurred_year": 2023, "fatal": True, "involves_bicycle": False},
        ]
        run_row = await accident_conn.fetchrow(
            "SELECT status, occurred_year, accident_count FROM accident_import_runs"
        )
        assert run_row["status"] == "succeeded"
        assert run_row["occurred_year"] == 2023
        assert run_row["accident_count"] == 2

    async def test_upserts_same_accident_id_on_rerun(self, accident_conn, tmp_path, monkeypatch):
        monkeypatch.setattr(import_accidents, "DATA_DIR", tmp_path)
        csv_path = tmp_path / "honhyo_2023.csv"
        _write_csv(csv_path, [_make_row(prefecture_code="30", death_count="000")])
        assert await run_import([2023], TEST_DATABASE_URL, dry_run=False) == 0

        # 同じaccident_idで死者数だけ変わった再取込（年次CSVの更新を想定）。
        csv_path.unlink()
        _write_csv(csv_path, [_make_row(prefecture_code="30", death_count="001")])
        assert await run_import([2023], TEST_DATABASE_URL, dry_run=False) == 0

        rows = await accident_conn.fetch("SELECT accident_id, fatal FROM accident_points")
        assert len(rows) == 1  # 重複INSERTされない（ON CONFLICT DO UPDATE）
        assert rows[0]["fatal"] is True  # 新しい値へ更新されている
        run_count = await accident_conn.fetchval("SELECT count(*) FROM accident_import_runs")
        assert run_count == 2  # runごとの実行記録は積み上がる

    async def test_dry_run_does_not_touch_db(self, accident_conn, tmp_path, monkeypatch):
        monkeypatch.setattr(import_accidents, "DATA_DIR", tmp_path)
        _write_csv(tmp_path / "honhyo_2023.csv", [_make_row(prefecture_code="30")])

        result = await run_import([2023], TEST_DATABASE_URL, dry_run=True)

        assert result == 0
        assert await accident_conn.fetchval("SELECT count(*) FROM accident_points") == 0
        assert await accident_conn.fetchval("SELECT count(*) FROM accident_import_runs") == 0

    async def test_returns_error_when_no_csv_available(self, tmp_path, monkeypatch):
        # DATA_DIRにファイルが無く、HTTP取得も失敗する（実ネットワークへは出ない）場合、
        # DB接続自体を試みずrun_importが1を返すことを確認する（csv_paths空時の早期return、
        # DB fixture不要＝DB未起動でも実行できるテスト）。
        monkeypatch.setattr(import_accidents, "DATA_DIR", tmp_path)

        def _raise_connect_error(self, method, url, **kwargs):
            raise httpx.ConnectError("boom", request=httpx.Request(method, url))

        monkeypatch.setattr(httpx.AsyncClient, "stream", _raise_connect_error)

        result = await run_import([2023], TEST_DATABASE_URL, dry_run=False)

        assert result == 1

    async def test_marks_run_failed_and_reraises_when_merge_fails(self, accident_conn, tmp_path, monkeypatch):
        monkeypatch.setattr(import_accidents, "DATA_DIR", tmp_path)
        _write_csv(tmp_path / "honhyo_2023.csv", [_make_row(prefecture_code="30")])

        async def _boom(*args, **kwargs):
            raise RuntimeError("boom")

        # asyncpg.Connectionはインスタンス属性の上書きを許さない（__slots__）ため、
        # クラス側のメソッドをmonkeypatchする（test_import_designations.pyと同じ手法）。
        monkeypatch.setattr(asyncpg.Connection, "copy_records_to_table", _boom)

        with pytest.raises(RuntimeError):
            await run_import([2023], TEST_DATABASE_URL, dry_run=False)

        run_row = await accident_conn.fetchrow("SELECT status FROM accident_import_runs")
        assert run_row["status"] == "failed"
        assert await accident_conn.fetchval("SELECT count(*) FROM accident_points") == 0
