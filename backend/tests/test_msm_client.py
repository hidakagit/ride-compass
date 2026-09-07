"""MSMの同期・読み出し（infrastructure/msm_client.py）のテスト。

読み出しは実際の`.om`ファイルを書き出して確認する（omfilesのReader/Writerを通すため、
配列の並び・スライスの解釈がずれれば検出できる）。同期はhttpx.MockTransportで
配信元を差し替え、ETagによる条件付きGETと不要チャンクの削除を確認する。
"""

import json

import httpx
import numpy as np
import pytest
from omfiles import OmFileWriter

from app.config import settings
from app.infrastructure import msm_client
from app.infrastructure.msm_client import MsmUnavailableError

CHUNK_HOURS = 6
N_LAT = N_LON = 11
BBOX = "BBOX[30.0,130.0,40.0,140.0]"
# 格子間隔が1度になるbbox・形状。緯度30度・経度130度が索引(0, 0)。


def _meta(data_end_time: int) -> dict:
    return {
        "chunk_time_length": CHUNK_HOURS,
        "crs_wkt": f'GEOGCRS["WGS 84", USAGE[SCOPE["grid"], {BBOX}]]',
        "data_end_time": data_end_time,
        "last_run_initialisation_time": data_end_time - 3600,
        "temporal_resolution_seconds": 3600,
        "update_interval_seconds": 10800,
    }


def _write_chunk(path, value_at):
    """[緯度, 経度, 時刻]の`.om`を書く。`value_at(i, j, t)`が各要素の値。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.fromfunction(np.vectorize(value_at), (N_LAT, N_LON, CHUNK_HOURS), dtype=int).astype(np.float32)
    writer = OmFileWriter.at_path(str(path))
    variable = writer.write_array(data, chunks=[N_LAT, N_LON, CHUNK_HOURS])
    writer.close(variable)


@pytest.fixture
def msm_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(msm_client, "MSM_DIR", tmp_path)
    monkeypatch.setattr(msm_client, "_META_FILE", tmp_path / "meta.json")
    monkeypatch.setattr(msm_client, "_ETAGS_FILE", tmp_path / "etags.json")
    return tmp_path


@pytest.fixture
def frozen_now(monkeypatch):
    """同期対象のチャンク番号は現在時刻から決まるため、時刻を固定して結果を決定的にする。"""
    now = msm_client._chunk_start(100_000, CHUNK_HOURS)
    monkeypatch.setattr(msm_client.time, "time", lambda: float(now))
    return now


def _prepare(msm_dir, now: int, data_end_time: int, value_at=lambda i, j, t: i * 100 + j * 10 + t) -> int:
    """`now`を含むチャンクを全変数ぶん書き、メタ情報を保存する。チャンク番号を返す。"""
    (msm_dir / "meta.json").write_text(json.dumps(_meta(data_end_time)), encoding="utf-8")
    chunk_number = msm_client._chunk_number(now, CHUNK_HOURS)
    for variable in msm_client.WIND_VARIABLES:
        _write_chunk(msm_dir / variable / f"chunk_{chunk_number}.om", value_at)
    return chunk_number


def test_chunk_number_and_start_are_consistent():
    number = msm_client._chunk_number(1_788_754_800, CHUNK_HOURS)
    start = msm_client._chunk_start(number, CHUNK_HOURS)

    assert start <= 1_788_754_800 < start + CHUNK_HOURS * 3600


def test_read_series_returns_interpolated_values_and_jst_times(msm_dir):
    now = msm_client._chunk_start(100_000, CHUNK_HOURS)  # チャンク先頭の正時
    _prepare(msm_dir, now, data_end_time=now + CHUNK_HOURS * 3600)

    times, values = msm_client._read_series_sync(np.array([30.0]), np.array([130.0]), hours=3, now=now)

    assert len(times) == 3
    # 索引(0, 0)の格子点そのものを指すため、時刻ごとの値がそのまま出る。
    assert values["wind_u_component_10m"][0].tolist() == [0.0, 1.0, 2.0]
    # JSTのISO文字列（分まで、タイムゾーン表記なし）で返す。
    assert times[0].endswith(":00")
    assert len(times[0]) == len("2026-09-07T13:00")


def test_read_series_interpolates_between_grid_points(msm_dir):
    now = msm_client._chunk_start(100_000, CHUNK_HOURS)
    _prepare(msm_dir, now, data_end_time=now + CHUNK_HOURS * 3600)

    _times, values = msm_client._read_series_sync(np.array([30.5]), np.array([130.5]), hours=1, now=now)

    # 索引(0,0)=0, (1,0)=100, (0,1)=10, (1,1)=110 の中点。
    assert values["wind_u_component_10m"][0, 0] == pytest.approx(55.0)


def test_read_series_truncates_at_data_end(msm_dir):
    now = msm_client._chunk_start(100_000, CHUNK_HOURS)
    _prepare(msm_dir, now, data_end_time=now + 2 * 3600)

    times, values = msm_client._read_series_sync(np.array([30.0]), np.array([130.0]), hours=48, now=now)

    assert len(times) == 2
    assert values["precipitation"].shape == (1, 2)


def test_read_series_spans_consecutive_chunks(msm_dir):
    now = msm_client._chunk_start(100_000, CHUNK_HOURS)
    chunk = _prepare(msm_dir, now, data_end_time=now + 2 * CHUNK_HOURS * 3600)
    for variable in msm_client.WIND_VARIABLES:
        _write_chunk(msm_dir / variable / f"chunk_{chunk + 1}.om", lambda i, j, t: 1000 + t)

    times, values = msm_client._read_series_sync(np.array([30.0]), np.array([130.0]), hours=CHUNK_HOURS + 2, now=now)

    assert len(times) == CHUNK_HOURS + 2
    # 後半は次のチャンクの値が続く。
    assert values["wind_u_component_10m"][0, CHUNK_HOURS:].tolist() == [1000.0, 1001.0]


def test_read_series_raises_when_not_synced(msm_dir):
    with pytest.raises(MsmUnavailableError):
        msm_client._read_series_sync(np.array([30.0]), np.array([130.0]), hours=1, now=100_000)


def test_read_series_raises_when_forecast_is_behind_now(msm_dir):
    now = msm_client._chunk_start(100_000, CHUNK_HOURS)
    _prepare(msm_dir, now, data_end_time=now - 3600)

    with pytest.raises(MsmUnavailableError):
        msm_client._read_series_sync(np.array([30.0]), np.array([130.0]), hours=48, now=now)


def test_read_series_raises_when_chunk_file_missing(msm_dir):
    now = msm_client._chunk_start(100_000, CHUNK_HOURS)
    (msm_dir / "meta.json").write_text(json.dumps(_meta(now + 3600)), encoding="utf-8")

    with pytest.raises(MsmUnavailableError):
        msm_client._read_series_sync(np.array([30.0]), np.array([130.0]), hours=1, now=now)


class _FakeOrigin:
    """配信元の代わり。ETagを持ち、If-None-Matchが一致すれば304を返す。"""

    def __init__(self, meta: dict):
        self.meta = meta
        self.etag = '"v1"'
        self.body_requests: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("static/meta.json"):
            return httpx.Response(200, json=self.meta)
        if request.headers.get("If-None-Match") == self.etag:
            return httpx.Response(304)
        self.body_requests.append(path)
        return httpx.Response(200, content=b"om-bytes", headers={"ETag": self.etag})


async def test_refresh_downloads_chunks_and_records_etags(msm_dir, frozen_now, monkeypatch):
    monkeypatch.setattr(settings, "msm_base_url", "https://example.test/jma_msm")
    origin = _FakeOrigin(_meta(2_000_000))
    client = httpx.AsyncClient(transport=httpx.MockTransport(origin.handler))

    downloaded = await msm_client.refresh(client, horizon_hours=1)

    assert downloaded == len(msm_client.WIND_VARIABLES)
    assert json.loads((msm_dir / "meta.json").read_text(encoding="utf-8"))["chunk_time_length"] == CHUNK_HOURS
    assert len(json.loads((msm_dir / "etags.json").read_text(encoding="utf-8"))) == len(msm_client.WIND_VARIABLES)
    for variable in msm_client.WIND_VARIABLES:
        assert list((msm_dir / variable).glob("chunk_*.om"))
    await client.aclose()


async def test_refresh_skips_unchanged_chunks(msm_dir, frozen_now, monkeypatch):
    monkeypatch.setattr(settings, "msm_base_url", "https://example.test/jma_msm")
    origin = _FakeOrigin(_meta(2_000_000))
    client = httpx.AsyncClient(transport=httpx.MockTransport(origin.handler))

    await msm_client.refresh(client, horizon_hours=1)
    origin.body_requests.clear()
    downloaded = await msm_client.refresh(client, horizon_hours=1)

    # 2回目は条件付きGETが304になり、本体の転送自体が起きない。
    assert downloaded == 0
    assert origin.body_requests == []
    await client.aclose()


async def test_refresh_removes_chunks_outside_the_forecast_window(msm_dir, frozen_now, monkeypatch):
    monkeypatch.setattr(settings, "msm_base_url", "https://example.test/jma_msm")
    origin = _FakeOrigin(_meta(2_000_000))
    client = httpx.AsyncClient(transport=httpx.MockTransport(origin.handler))
    stale = msm_dir / msm_client.WIND_VARIABLES[0] / "chunk_1.om"  # 予報窓の外の古いチャンク
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_bytes(b"old")

    await msm_client.refresh(client, horizon_hours=1)

    assert not stale.exists()
    await client.aclose()
