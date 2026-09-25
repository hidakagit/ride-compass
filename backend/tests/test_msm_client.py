"""`infrastructure/msm_client.py`——気象庁MSMの予報を配信元と同期し、ローカルの`.om`ファイルから読む。

確かめるのは公開の入口（`refresh`・`read_series`・`freshness`/`freshness_from_meta`/`warn_if_stale`・
`update_interval_seconds`）から見える振る舞いだけ。差し替えるのはプロセス境界だけで、網は本物の
`httpx.AsyncClient`へ配信元の代役（`MockTransport`）を付け、ディスクは一時ディレクトリ、時計は固定する。
`.om`ファイルは本物のライブラリ（omfiles）で書く。

ここで見ないもの:
- 格子の幾何と双一次補間そのもの → `test_msm.py`
- 予報を天候・風へ組み立てる側 → `test_weather_service.py`

予報の値は「格子点(i, j)・チャンク内の時刻tで 100i + 10j + t（チャンクごとに1000ずつ足す）」にしてある。
補間した値の期待値が足し算で書ける。チャンクの番号は配信元の決まり（1970年からの経過時間÷チャンクの長さ）。
"""

import logging
from datetime import datetime
from types import SimpleNamespace

import httpx
import numpy as np
import pytest
from omfiles import OmFileWriter

from app.domain.time_zone import JST
from app.infrastructure import msm_client
from app.infrastructure.msm_client import MsmUnavailableError

CHUNK_HOURS = 6
#: 2026-09-22 05:30 JST。6時間のチャンクは03:00 JSTに始まるので、先頭から2時間30分に当たる。
NOW = int(datetime(2026, 9, 22, 5, 30, tzinfo=JST).timestamp())
NOW_CHUNK = (NOW // 3600) // CHUNK_HOURS
CHUNK_START = NOW_CHUNK * CHUNK_HOURS * 3600
#: 格子は南緯35.0・西経139.0から0.05度おきに3×3。
BBOX_WKT = 'GEOGCRS["x", BBOX[35.0, 139.0, 35.1, 139.1]]'
SOUTH_WEST = (35.0, 139.0)
#: 南西の格子点と北隣の格子点のちょうど中間（i=0.5, j=0）。
HALF_NORTH = (35.025, 139.0)


def _meta(**overrides):
    meta = {
        "chunk_time_length": CHUNK_HOURS,
        "crs_wkt": BBOX_WKT,
        "data_end_time": CHUNK_START + 3 * CHUNK_HOURS * 3600,
        "last_run_initialisation_time": NOW - 3 * 3600,
        "last_run_availability_time": NOW - 1 * 3600,
        "update_interval_seconds": 3 * 3600,
    }
    meta.update(overrides)
    return meta


def _chunk_values(chunk_number: int) -> np.ndarray:
    i, j, t = np.meshgrid(np.arange(3), np.arange(3), np.arange(CHUNK_HOURS), indexing="ij")
    return (100 * i + 10 * j + t + 1000 * (chunk_number - NOW_CHUNK)).astype(np.float32)


def _om_bytes(tmp_path, chunk_number: int) -> bytes:
    path = tmp_path / f"source_{chunk_number}.om"
    writer = OmFileWriter.at_path(str(path))
    writer.close(writer.write_array(_chunk_values(chunk_number), chunks=[3, 3, CHUNK_HOURS]))
    return path.read_bytes()


@pytest.fixture
def msm_dir(tmp_path, monkeypatch):
    """同期先のディスクを一時ディレクトリへ、時計を`NOW`へ。"""
    directory = tmp_path / "msm"
    monkeypatch.setattr(msm_client, "MSM_DIR", directory)
    monkeypatch.setattr(msm_client, "_META_FILE", directory / "meta.json")
    monkeypatch.setattr(msm_client, "_ETAGS_FILE", directory / "etags.json")
    clock = SimpleNamespace(now=NOW)
    monkeypatch.setattr(msm_client, "time", SimpleNamespace(time=lambda: clock.now))
    return SimpleNamespace(path=directory, clock=clock)


class Source:
    """配信元の代役。チャンクはETagを付けて返し、`If-None-Match`が一致すれば304を返す。"""

    def __init__(self, tmp_path, meta=None):
        self.tmp_path = tmp_path
        self.meta = meta if meta is not None else _meta()
        self.requests: list[httpx.Request] = []
        self.fail: set[str] = set()

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        name = request.url.path.rsplit("/", 2)
        if "meta" in self.fail and name[-1] == "meta.json":
            return httpx.Response(500)
        if name[-1] == "meta.json":
            return httpx.Response(200, json=self.meta) if isinstance(self.meta, dict) else httpx.Response(200, content=self.meta)
        chunk_number = int(name[-1].removeprefix("chunk_").removesuffix(".om"))
        if "chunk" in self.fail:
            return httpx.Response(500)
        etag = f'"{name[-2]}-{chunk_number}"'
        if request.headers.get("If-None-Match") == etag:
            return httpx.Response(304)
        return httpx.Response(200, content=_om_bytes(self.tmp_path, chunk_number), headers={"ETag": etag})

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handle))

    def chunk_requests(self):
        return [r for r in self.requests if r.url.path.endswith(".om")]


async def _synced(tmp_path, msm_dir, meta=None, horizon_hours=CHUNK_HOURS):
    source = Source(tmp_path, meta)
    async with source.client() as client:
        await msm_client.refresh(client, horizon_hours=horizon_hours)
    return source


def _points(*points):
    return np.array([p[0] for p in points]), np.array([p[1] for p in points])


# --- 同期（refresh） ---


class TestSyncing:
    async def test_every_variable_is_fetched_for_the_chunks_covering_the_horizon(self, tmp_path, msm_dir):
        """今のチャンクと、`horizon_hours`先を含むチャンク。3時間先は今のチャンクの中、6時間先は次のチャンク。

        配信元のチャンク（実際は114時間）は予報窓より長いため、取るのは多くて2つ。
        """
        source = Source(tmp_path)
        async with source.client() as client:
            within = await msm_client.refresh(client, horizon_hours=3)
            beyond = await msm_client.refresh(client, horizon_hours=6)

        variables = len(msm_client.FORECAST_VARIABLES)
        assert within == variables
        assert beyond == variables  # 今のチャンクは変わっていないので、取るのは次のチャンクだけ
        fetched = {r.url.path.rsplit("/", 1)[-1] for r in source.chunk_requests()}
        assert fetched == {f"chunk_{NOW_CHUNK}.om", f"chunk_{NOW_CHUNK + 1}.om"}

    async def test_a_chunk_the_source_has_not_changed_is_not_transferred_again(self, tmp_path, msm_dir):
        source = Source(tmp_path)
        async with source.client() as client:
            await msm_client.refresh(client, horizon_hours=3)
            again = await msm_client.refresh(client, horizon_hours=3)

        assert again == 0

    async def test_a_chunk_whose_file_was_lost_is_fetched_again_even_with_a_known_etag(self, tmp_path, msm_dir):
        """「変更なし」を信じて、無いファイルを読みに行かない。"""
        source = Source(tmp_path)
        async with source.client() as client:
            await msm_client.refresh(client, horizon_hours=3)
            variable = msm_client.FORECAST_VARIABLES[0]
            (msm_dir.path / variable / f"chunk_{NOW_CHUNK}.om").unlink()
            again = await msm_client.refresh(client, horizon_hours=3)

        assert again == 1
        assert (msm_dir.path / variable / f"chunk_{NOW_CHUNK}.om").exists()

    async def test_chunks_no_longer_covered_are_removed(self, tmp_path, msm_dir):
        """1ファイル十数MBあるため、予報に使わなくなった過去のチャンクを残さない。"""
        source = Source(tmp_path)
        async with source.client() as client:
            await msm_client.refresh(client, horizon_hours=3)
            msm_dir.clock.now = NOW + CHUNK_HOURS * 3600
            await msm_client.refresh(client, horizon_hours=3)

        for variable in msm_client.FORECAST_VARIABLES:
            names = {p.name for p in (msm_dir.path / variable).glob("chunk_*.om")}
            assert names == {f"chunk_{NOW_CHUNK + 1}.om"}

    async def test_after_syncing_the_schedule_of_the_source_is_readable(self, tmp_path, msm_dir):
        assert msm_client.freshness() is None
        assert msm_client.update_interval_seconds(default=60) == 60

        await _synced(tmp_path, msm_dir, _meta(update_interval_seconds=7200))

        assert msm_client.freshness() is not None
        assert msm_client.update_interval_seconds(default=60) == 7200

    @pytest.mark.parametrize("failing", ["meta", "chunk"])
    async def test_a_failed_request_to_the_source_is_raised(self, tmp_path, msm_dir, failing):
        """同期の失敗を黙って成功扱いにしない（呼び出し元の定期ジョブが警告にする）。"""
        source = Source(tmp_path)
        source.fail.add(failing)
        async with source.client() as client:
            with pytest.raises(httpx.HTTPStatusError):
                await msm_client.refresh(client, horizon_hours=3)

    async def test_meta_information_that_is_not_json_is_raised(self, tmp_path, msm_dir):
        source = Source(tmp_path, meta=b"<html>maintenance</html>")
        async with source.client() as client:
            with pytest.raises(ValueError):
                await msm_client.refresh(client, horizon_hours=3)

    async def test_syncing_a_source_that_stopped_publishing_warns(self, tmp_path, msm_dir, caplog):
        """ETagで304が続くと件数からは止まったことが分からない。公開の経過で気づく。"""
        stale = _meta(last_run_availability_time=NOW - 7 * 3600)
        with caplog.at_level(logging.WARNING, logger="ridecompass.msm_client"):
            await _synced(tmp_path, msm_dir, stale, horizon_hours=3)

        assert any("公開されていません" in r.getMessage() for r in caplog.records)


# --- 読み出し（read_series） ---


class TestReading:
    async def test_series_start_at_the_current_hour_in_japan_time(self, tmp_path, msm_dir):
        await _synced(tmp_path, msm_dir)

        times, values = await msm_client.read_series(*_points(SOUTH_WEST), hours=3)

        assert times == ["2026-09-22T05:00", "2026-09-22T06:00", "2026-09-22T07:00"]
        assert set(values) == set(msm_client.FORECAST_VARIABLES)
        assert all(array.shape == (1, 3) for array in values.values())

    async def test_each_point_is_interpolated_between_the_grid_points_around_it(self, tmp_path, msm_dir):
        """南西の格子点はそのまま、北隣との中間は2点の平均（100i + 10j + t で i=0.5）。"""
        await _synced(tmp_path, msm_dir)

        _, values = await msm_client.read_series(*_points(SOUTH_WEST, HALF_NORTH), hours=2)

        # 05:00はチャンクの先頭から2時間目（t=2）。
        assert values["temperature_2m"] == pytest.approx(np.array([[2.0, 3.0], [52.0, 53.0]]))

    async def test_a_series_crossing_into_the_next_chunk_continues_from_it(self, tmp_path, msm_dir):
        await _synced(tmp_path, msm_dir)

        times, values = await msm_client.read_series(*_points(SOUTH_WEST), hours=6)

        assert times[3:] == ["2026-09-22T08:00", "2026-09-22T09:00", "2026-09-22T10:00"]
        assert values["precipitation"][0].tolist() == [2.0, 3.0, 4.0, 5.0, 1000.0, 1001.0]

    async def test_a_series_stops_where_the_forecast_ends(self, tmp_path, msm_dir):
        """予報の終端より先は読めない。求めた長さより短い系列が返る。"""
        await _synced(tmp_path, msm_dir, _meta(data_end_time=NOW - NOW % 3600 + 2 * 3600))

        times, _ = await msm_client.read_series(*_points(SOUTH_WEST), hours=24)

        assert times == ["2026-09-22T05:00", "2026-09-22T06:00"]

    async def test_a_forecast_that_ended_before_now_cannot_be_read(self, tmp_path, msm_dir):
        await _synced(tmp_path, msm_dir, _meta(data_end_time=NOW - NOW % 3600))

        with pytest.raises(MsmUnavailableError):
            await msm_client.read_series(*_points(SOUTH_WEST), hours=3)

    async def test_nothing_can_be_read_before_the_first_sync(self, msm_dir):
        with pytest.raises(MsmUnavailableError):
            await msm_client.read_series(*_points(SOUTH_WEST), hours=3)

    @pytest.mark.parametrize("variable_index", [0, -1])
    @pytest.mark.parametrize("missing_chunk", [NOW_CHUNK, NOW_CHUNK + 1])
    async def test_a_chunk_that_has_not_been_synced_cannot_be_read(self, tmp_path, msm_dir, missing_chunk, variable_index):
        await _synced(tmp_path, msm_dir)
        variable = msm_client.FORECAST_VARIABLES[variable_index]
        (msm_dir.path / variable / f"chunk_{missing_chunk}.om").unlink()

        with pytest.raises(MsmUnavailableError):
            await msm_client.read_series(*_points(SOUTH_WEST), hours=6)

    async def test_a_point_outside_the_grid_is_refused(self, tmp_path, msm_dir):
        await _synced(tmp_path, msm_dir)

        with pytest.raises(ValueError):
            await msm_client.read_series(*_points((36.0, 139.0)), hours=3)


# --- 鮮度 ---


def _freshness(**overrides):
    return msm_client.freshness_from_meta(_meta(**overrides), now=datetime.fromtimestamp(NOW, JST))


class TestFreshness:
    def test_ages_and_remaining_hours_are_measured_from_now(self):
        value = _freshness()

        assert value.run_age_hours == pytest.approx(3.0)
        assert value.publish_age_hours == pytest.approx(1.0)
        assert value.remaining_hours == pytest.approx(15.5)
        assert value.stale_threshold_hours == pytest.approx(6.0)  # 3時間ごとの公開を2回続けて落とした

    def test_a_source_without_a_publication_time_is_judged_by_the_run_time(self):
        """公開遅れのぶん早く「止まった」と言う側に倒れる。"""
        value = _freshness(last_run_availability_time=None)

        assert value.publish_age_hours == pytest.approx(3.0)

    @pytest.mark.parametrize("missing", ["last_run_initialisation_time", "data_end_time"])
    def test_meta_without_the_run_or_the_end_of_the_forecast_has_no_freshness(self, missing):
        assert _freshness(**{missing: None}) is None

    @pytest.mark.parametrize(("hours_since_publication", "stale"), [(5.9, False), (6.0, True)])
    def test_the_source_counts_as_stopped_from_two_missed_publications(self, hours_since_publication, stale):
        value = _freshness(last_run_availability_time=NOW - int(hours_since_publication * 3600))

        assert value.run_is_stale is stale
        assert value.is_healthy is (not stale and not value.horizon_is_short)

    @pytest.mark.parametrize(("remaining_hours", "short"), [(12.0, False), (11.9, True)])
    def test_the_forecast_counts_as_running_out_below_twelve_hours(self, remaining_hours, short):
        value = _freshness(data_end_time=NOW + int(remaining_hours * 3600))

        assert value.horizon_is_short is short
        assert value.is_healthy is not short

    def test_a_run_published_recently_is_not_stopped_however_old_the_run_itself_is(self):
        """初期時刻からの経過は公開遅れのぶん常に長く、次の公開まで伸び続ける。そちらで判定すると正常時にも止まったと言う。"""
        value = _freshness(last_run_initialisation_time=NOW - 7 * 3600, last_run_availability_time=NOW - 3600)

        assert value.run_age_hours > value.stale_threshold_hours
        assert value.run_is_stale is False

    def test_the_stop_threshold_follows_the_update_interval_the_source_announces(self):
        assert _freshness(update_interval_seconds=3600).stale_threshold_hours == pytest.approx(2.0)

    @pytest.mark.parametrize("interval", [0, -1, "3h", None])
    def test_an_unusable_update_interval_falls_back_to_three_hours(self, interval):
        assert _freshness(update_interval_seconds=interval).stale_threshold_hours == pytest.approx(6.0)


class TestWarningAboutFreshness:
    def _warnings(self, caplog, value):
        with caplog.at_level(logging.WARNING, logger="ridecompass.msm_client"):
            msm_client.warn_if_stale(value)
        return [r.getMessage() for r in caplog.records]

    def test_unknown_freshness_is_warned_about(self, caplog):
        assert any("判定できません" in m for m in self._warnings(caplog, None))

    def test_a_healthy_source_is_not_warned_about(self, caplog):
        assert self._warnings(caplog, _freshness()) == []

    def test_a_stopped_source_and_a_forecast_running_out_are_each_warned_about(self, caplog):
        value = _freshness(last_run_availability_time=NOW - 7 * 3600, data_end_time=NOW + 3600)

        messages = self._warnings(caplog, value)

        assert any("公開されていません" in m for m in messages)
        assert any("尽きかけています" in m for m in messages)


def test_an_unreadable_schedule_on_disk_uses_the_default_interval(msm_dir):
    msm_dir.path.mkdir()
    (msm_dir.path / "meta.json").write_text("{broken", encoding="utf-8")

    assert msm_client.update_interval_seconds(default=60) == 60
