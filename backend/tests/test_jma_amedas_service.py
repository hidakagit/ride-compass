"""jma_amedas_service.pyのテスト。

差し替えるのはプロセス境界だけ——気象庁への取得は応答の形のままURLごとに返すrespxの経路
（アメダスのJSONと推計気象分布の時刻一覧・タイルのPNG）、Redisはfakeredis（`fake_redis`）。
応答の形を解くクライアントは本物を通す。

JMAの観測値エンドポイントは1地点だけを絞り込めず全国分を1レスポンスで返すため、取得は
`refresh_all_stations`（main.pyの定期バッチが呼ぶ）が一括で担い、`get_nearest_observation`
（リクエスト経路）はRedis読み取り専用である。
"""

import io
import json
from datetime import datetime, timedelta

import httpx
import numpy as np
import pytest
import respx
from cachetools import TTLCache
from PIL import Image

from app.domain.jma_amedas import apparent_temperature_from_amedas
from app.domain.jma_suikei import SUIKEI_TARGET_TIMES_PATH
from app.domain.rain import HOURS_SINCE_RAIN, RAIN_HISTORY_HOURS, RAIN_HISTORY_MAX_AGE, rain_window_material_id
from app.domain.route import Coordinates
from app.domain.time_zone import JST
from app.infrastructure import jma_amedas_client, jma_amedas_store, jma_tile_client
from app.services.jma_amedas_service import JmaAmedasService, load_station_rain_materials
from tests import rain_history_fake
from tests.fake_http import client_for

POINT = Coordinates(latitude=35.68, longitude=139.76)
LATEST_TIME = "2026-08-29T12:00:00+09:00"

STATIONS = {
    "44132": {"lat": [35, 41.4], "lon": [139, 45.6], "kjName": "東京"},
    "99999": {"lat": [0, 0], "lon": [0, 0], "kjName": "遠い場所"},
}

OBSERVATION_MAP = {
    "44132": {
        "temp": [26.5, 0],
        "humidity": [70, 0],
        "wind": [3.5, 0],
        "windDirection": [8, 0],
        "precipitation10m": [0.0, 0],
        "sun10m": [5.0, 0],
    },
    "99999": {
        "temp": [10.0, 0],
        "wind": [1.0, 0],
        "windDirection": [1, 0],
        "precipitation10m": [0.0, 0],
        # 湿度センサー無し（雨量計のみ等）の観測所を再現——体感温度はNoneのままになるはず。
    },
}


# 推計気象分布の凡例の色（気象庁の公式の画面の凡例）。
CLEAR = (255, 170, 0, 255)
CLOUDY = (170, 170, 170, 255)
RAIN = (0, 65, 255, 255)
SUIKEI_ROOT = f"{jma_tile_client.UPSTREAM_HOST}/bosai/jmatile/data/suikeikishou"
SUIKEI_LATEST = "20260829030000"
SUIKEI_TARGET_TIMES = [
    {"basetime": SUIKEI_LATEST, "validtime": SUIKEI_LATEST, "elements": ["temp", "wthr", "suns1h"]},
    {"basetime": "20260829020000", "validtime": "20260829020000", "elements": ["temp", "wthr", "suns1h"]},
]
# `POINT`を含む天気のタイル（パスのズーム10。512画素のタイルを1辺512枚で数える）と、その中の画素の列・行。
# 気象庁の公式の画面が東京付近で取りに行くタイルと同じ座標。
POINT_TILE = (454, 201)
POINT_PIXEL = (394, 315)


def suikei_tile(color_at_point, elsewhere=CLOUDY) -> bytes:
    """`POINT`の画素だけを`color_at_point`で、ほかを`elsewhere`で塗った、配信元と同じパレットのPNG。"""
    image = Image.new("RGBA", (512, 512), elsewhere)
    image.putpixel(POINT_PIXEL, color_at_point)
    buffer = io.BytesIO()
    image.convert("P").save(buffer, format="PNG")
    return buffer.getvalue()


def _router(
    *,
    stations=STATIONS,
    latest_time=LATEST_TIME,
    observation_map=lambda timestamp: OBSERVATION_MAP,
    suikei_target_times=SUIKEI_TARGET_TIMES,
    suikei=suikei_tile(CLOUDY),
):
    """気象庁アメダスと推計気象分布の代役。観測値は要求された時刻（URLの`YYYYMMDDHHMMSS`）ごとに
    `observation_map`が返す。どれもNoneなら、その取得は接続の失敗になる。推計気象分布のタイルは、最新の時刻の
    `POINT`を含むタイルだけを`suikei`（PNG。Noneなら404）で返す。"""
    prefix, suffix = jma_amedas_client.AMEDAS_OBSERVATION_URL_TEMPLATE.split("{timestamp}")

    def observation(request):
        payload = observation_map(str(request.url).removeprefix(prefix).removesuffix(suffix))
        if payload is None:
            raise httpx.ConnectError("unreachable", request=request)
        return httpx.Response(200, json=payload)

    upstream = respx.Router()
    table = upstream.get(jma_amedas_client.AMEDAS_STATION_TABLE_URL)
    if stations is None:
        table.mock(side_effect=httpx.ConnectError)
    else:
        table.respond(json=stations)
    latest = upstream.get(jma_amedas_client.AMEDAS_LATEST_TIME_URL)
    if latest_time is None:
        latest.mock(side_effect=httpx.ConnectError)
    else:
        latest.respond(text=latest_time)
    upstream.get(url__startswith=prefix).mock(side_effect=observation)
    target_times = upstream.get(f"{jma_tile_client.UPSTREAM_HOST}/{SUIKEI_TARGET_TIMES_PATH}")
    if suikei_target_times is None:
        target_times.mock(side_effect=httpx.ConnectError)
    else:
        target_times.respond(json=suikei_target_times)
    tile = upstream.get(f"{SUIKEI_ROOT}/{SUIKEI_LATEST}/none/{SUIKEI_LATEST}/surf/wthr/10/{POINT_TILE[0]}/{POINT_TILE[1]}.png")
    if suikei is None:
        tile.respond(404)
    else:
        tile.respond(content=suikei, headers={"content-type": "image/png"})
    return upstream


def _upstream(**answers):
    return client_for(_router(**answers))


def _forget_client_caches(monkeypatch):
    """クライアントのプロセス内キャッシュ（観測所マスタ・最新時刻）を空にする。テストをまたいで残り、
    同じテストの中でも最新時刻を変えて引き直すときに古い値が返るため。"""
    monkeypatch.setattr(jma_amedas_client, "station_table_cache", TTLCache(maxsize=1, ttl=60))
    monkeypatch.setattr(jma_amedas_client, "latest_time_cache", TTLCache(maxsize=1, ttl=60))


@pytest.fixture(autouse=True)
def _empty_stores(monkeypatch, fake_redis):
    """Redisは空から、クライアントのプロセス内キャッシュ（推計気象分布の時刻一覧も）も空から始める。"""
    _forget_client_caches(monkeypatch)
    monkeypatch.setattr(jma_tile_client, "target_times_cache", TTLCache(maxsize=16, ttl=60))
    monkeypatch.setattr(jma_tile_client, "last_fetch_at", None)


async def _hashes(redis) -> dict[str, dict[str, str]]:
    """Redisにあるハッシュ（観測所ごとの観測値）を、キーから中身へ。"""
    return {key: await redis.hgetall(key) for key in await redis.keys() if await redis.type(key) == "hash"}


async def test_refresh_all_stations_caches_every_station_in_one_batch(fake_redis):
    service = JmaAmedasService(http_client=_upstream())

    count = await service.refresh_all_stations()

    assert count == 2
    hashes = await _hashes(fake_redis)
    assert set(hashes) == {"jma:amedas:44132", "jma:amedas:99999"}
    assert hashes["jma:amedas:44132"]["station_name"] == "東京"
    expected_apparent = apparent_temperature_from_amedas(26.5, 70, 3.5)
    assert float(hashes["jma:amedas:44132"]["apparent_temperature_c"]) == expected_apparent
    # 湿度センサー無しの観測所（99999）は体感温度を計算できずNone（空文字）のまま。
    assert hashes["jma:amedas:99999"]["apparent_temperature_c"] == ""


async def test_refresh_all_stations_warns_when_station_table_fetch_fails(monkeypatch, caplog):
    # 呼び出し元は例外の有無しか見ないため、1件も書けていないことはサービス層自身が
    # WARNINGで残すしかない。
    service = JmaAmedasService(http_client=_upstream(stations=None))

    with caplog.at_level("WARNING", logger="ridecompass.jma_amedas_service"):
        count = await service.refresh_all_stations()

    assert count == 0
    assert any("観測所マスタ" in record.message for record in caplog.records)


async def test_refresh_all_stations_warns_when_latest_observation_time_fetch_fails(monkeypatch, caplog):
    service = JmaAmedasService(http_client=_upstream(latest_time=None))

    with caplog.at_level("WARNING", logger="ridecompass.jma_amedas_service"):
        count = await service.refresh_all_stations()

    assert count == 0
    assert any("最新観測時刻" in record.message for record in caplog.records)


async def test_refresh_all_stations_warns_when_observation_map_fetch_fails(monkeypatch, caplog):
    service = JmaAmedasService(http_client=_upstream(observation_map=lambda timestamp: None))

    with caplog.at_level("WARNING", logger="ridecompass.jma_amedas_service"):
        count = await service.refresh_all_stations()

    assert count == 0
    assert any("観測値マップ" in record.message for record in caplog.records)


async def test_get_nearest_observation_reads_from_redis_without_fetching(monkeypatch):
    upstream = _router()
    service = JmaAmedasService(http_client=client_for(upstream))
    # バッチ（定期実行想定）が先に全国分をキャッシュ済みという前提を再現する。
    await service.refresh_all_stations()
    upstream.reset()

    result = await service.get_nearest_observation(POINT)

    # 観測所マスタはクライアントのキャッシュから引き、観測値は気象庁へ取りに行かない（取りに行くのは推計気象分布だけ）。
    assert upstream.calls
    assert all(str(call.request.url).startswith(SUIKEI_ROOT) for call in upstream.calls)
    assert result is not None
    assert result.station_id == "44132"
    assert result.station_name == "東京"
    assert result.temperature_c == 26.5
    assert result.apparent_temperature_c == apparent_temperature_from_amedas(26.5, 70, 3.5)
    assert result.wind_speed_ms == 3.5
    assert result.wind_direction is not None and result.wind_direction.label == "南"
    assert result.precipitation_10min_mm == 0.0
    # 日の出・日没はRedisには無く、クエリ地点に対してその場で計算される。
    assert result.twilight is not None


async def _nearest(**answers):
    service = JmaAmedasService(http_client=_upstream(**answers))
    await service.refresh_all_stations()
    return await service.get_nearest_observation(POINT)


def _at_night(precipitation_10min_mm):
    """夜の観測（日照計は空によらず0）。"""
    return lambda timestamp: {
        **OBSERVATION_MAP,
        "44132": {**OBSERVATION_MAP["44132"], "precipitation10m": [precipitation_10min_mm, 0], "sun10m": [0.0, 0]},
    }


@pytest.mark.parametrize(
    ("precipitation_10min_mm", "color_at_point", "expected"),
    [
        (0.0, CLEAR, 0),  # 晴れた夜は、日照が0でも晴れ
        (0.0, CLOUDY, 3),
        (0.0, RAIN, 3),  # 観測所で降っていなければ、推計の雨の区分は空のくもりとして出す
        (0.2, CLEAR, 63),  # 降っているかは観測所の実測が決める（10分0.2mm＝1時間1.2mm相当）
    ],
)
async def test_weather_code_takes_rain_from_the_station_and_the_sky_from_the_point(
    precipitation_10min_mm, color_at_point, expected
):
    result = await _nearest(observation_map=_at_night(precipitation_10min_mm), suikei=suikei_tile(color_at_point))

    assert result is not None
    assert result.weather_code == expected


async def test_sky_is_read_at_the_requested_point_not_around_it():
    result = await _nearest(observation_map=_at_night(0.0), suikei=suikei_tile(CLOUDY, elsewhere=CLEAR))

    assert result is not None
    assert result.weather_code == 3


@pytest.mark.parametrize(
    "answers",
    [
        {"suikei_target_times": None},  # 時刻一覧が取れない
        {"suikei": None},  # 描くものが無いタイル（推計の範囲の外）
        {"suikei": suikei_tile((1, 2, 3, 255))},  # 凡例に無い色
    ],
)
async def test_observation_is_still_returned_without_a_weather_code_when_the_sky_is_unknown(answers):
    result = await _nearest(observation_map=_at_night(0.0), **answers)

    assert result is not None
    assert result.temperature_c == 26.5
    assert result.weather_code is None


async def test_unknown_sky_is_logged_as_a_warning(caplog):
    with caplog.at_level("WARNING"):
        await _nearest(observation_map=_at_night(0.0), suikei_target_times=None)

    assert any("推計気象分布" in record.message for record in caplog.records)


async def test_get_nearest_observation_returns_none_when_not_yet_cached(monkeypatch):
    service = JmaAmedasService(http_client=_upstream())

    # refresh_all_stationsを呼んでいない（＝定期バッチがまだ一度も成功していない）状態。
    result = await service.get_nearest_observation(POINT)

    assert result is None


async def test_get_nearest_observation_fails_open_when_redis_client_unavailable(monkeypatch):
    # 設定ミス等でクライアント生成自体が失敗する場合、`get_redis_client_or_none`はNoneを
    # 返す。例外を外へ漏らさず「観測値なし」へ倒すこと。
    monkeypatch.setattr(jma_amedas_store, "get_redis_client_or_none", lambda: None)
    service = JmaAmedasService(http_client=_upstream())

    result = await service.get_nearest_observation(POINT)

    assert result is None


async def test_refresh_all_stations_fails_open_when_redis_client_unavailable(monkeypatch, caplog):
    # 書き込み側も同じfail-open契約を守る。書き込みだけをスキップし、バッチは完了する。
    monkeypatch.setattr(jma_amedas_store, "get_redis_client_or_none", lambda: None)
    service = JmaAmedasService(http_client=_upstream())

    count = await service.refresh_all_stations()

    # 観測値マップ自体の取得（JMA API側）は成功しているためcountは通常どおり返る。
    # Redisへの書き込みだけがスキップされる。
    assert count == 2


# --- 毎正時の1時間雨量の履歴（雨の材料の元） ---


@pytest.fixture(autouse=True)
def _fresh_rain_materials_cache(monkeypatch):
    rain_history_fake.forget_rain_materials(monkeypatch)


def _latest_hour(now: datetime) -> datetime:
    """直近の完全な正時の1つ前。観測時刻は正時の50分に置き、正時の地図JSONを別に取りに行かせる。"""
    return now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)


class RainMaps:
    """正時ごとの地図JSON。東京（44132）だけが雨量計を持ち、`rain_by_back`（何時間前の正時→mm）の雨を返す。"""

    def __init__(self, latest_hour: datetime, rain_by_back: dict[int, float], failing_backs: set[int] = frozenset()):
        self.latest_hour = latest_hour
        self.rain_by_back = rain_by_back
        self.failing_backs = set(failing_backs)
        self.requested_hours: list[int] = []

    def observation_map(self, timestamp):
        at = datetime.strptime(timestamp, "%Y%m%d%H%M%S").replace(tzinfo=JST)
        if at.minute != 0:
            return OBSERVATION_MAP
        back = int((self.latest_hour - at) / timedelta(hours=1))
        self.requested_hours.append(back)
        if back in self.failing_backs:
            return None
        rain = self.rain_by_back.get(back, 0.0)
        return {**OBSERVATION_MAP, "44132": {**OBSERVATION_MAP["44132"], "precipitation1h": [rain, 0]}}


def _rain_service(monkeypatch, maps: RainMaps) -> JmaAmedasService:
    _forget_client_caches(monkeypatch)
    latest_time = (maps.latest_hour + timedelta(minutes=50)).isoformat()
    return JmaAmedasService(http_client=_upstream(latest_time=latest_time, observation_map=maps.observation_map))


async def test_rain_history_is_backfilled_from_past_hourly_maps(monkeypatch):
    now = datetime.now(JST)
    maps = RainMaps(_latest_hour(now), rain_by_back={2: 3.0, 3: 3.0})

    await _rain_service(monkeypatch, maps).refresh_all_stations()
    materials = await load_station_rain_materials(now)

    assert sorted(maps.requested_hours) == list(range(RAIN_HISTORY_HOURS))
    assert materials is not None
    # 雨量計を持たない観測所（99999）は最寄りの候補に入らない。
    assert len(materials.latitudes) == 1
    assert materials.values[rain_window_material_id(1)][0] == 0.0
    assert materials.values[rain_window_material_id(3)][0] == 3.0
    assert materials.values[rain_window_material_id(4)][0] == 6.0
    assert materials.values[HOURS_SINCE_RAIN][0] == 2.0


async def test_rain_history_fetches_only_hours_it_does_not_have(monkeypatch):
    now = datetime.now(JST)
    latest_hour = _latest_hour(now)
    earlier = RainMaps(latest_hour - timedelta(hours=1), rain_by_back={})
    await _rain_service(monkeypatch, earlier).refresh_all_stations()

    later = RainMaps(latest_hour, rain_by_back={0: 1.5})
    await _rain_service(monkeypatch, later).refresh_all_stations()
    materials = await load_station_rain_materials(now)

    assert later.requested_hours == [0]
    assert materials is not None
    assert materials.values[rain_window_material_id(1)][0] == 1.5


async def test_an_hour_that_could_not_be_fetched_is_retried_and_leaves_its_windows_empty_meanwhile(monkeypatch):
    now = datetime.now(JST)
    latest_hour = _latest_hour(now)
    failing = RainMaps(latest_hour, rain_by_back={}, failing_backs={5})
    await _rain_service(monkeypatch, failing).refresh_all_stations()
    materials = await load_station_rain_materials(now)

    assert materials is not None
    assert materials.values[rain_window_material_id(4)][0] == 0.0
    assert np.isnan(materials.values[rain_window_material_id(6)][0])

    retry = RainMaps(latest_hour, rain_by_back={})
    await _rain_service(monkeypatch, retry).refresh_all_stations()

    assert retry.requested_hours == [5]


async def test_rain_history_is_not_refetched_while_redis_is_down(monkeypatch, redis_server):
    """置き場が使えないたびに全本を取り直すと、10分ごとに気象庁へ全本を問い合わせ続ける。"""
    redis_server.connected = False
    maps = RainMaps(_latest_hour(datetime.now(JST)), rain_by_back={})

    await _rain_service(monkeypatch, maps).refresh_all_stations()

    assert maps.requested_hours == []


async def test_rain_materials_are_not_served_from_a_stale_history(monkeypatch):
    now = datetime.now(JST)
    maps = RainMaps(_latest_hour(now), rain_by_back={})
    await _rain_service(monkeypatch, maps).refresh_all_stations()

    assert await load_station_rain_materials(now) is not None
    assert await load_station_rain_materials(maps.latest_hour + RAIN_HISTORY_MAX_AGE + timedelta(minutes=1)) is None


async def test_a_rain_history_stored_in_a_shape_that_cannot_be_read_serves_no_materials(monkeypatch, fake_redis):
    """保存した形は過去のコードが書いたもの。読めないまま展開すると、地図とルートの生成が500で落ちる。"""
    now = datetime.now(JST)
    await _rain_service(monkeypatch, RainMaps(_latest_hour(now), rain_by_back={})).refresh_all_stations()
    (key,) = [key for key in await fake_redis.keys() if await fake_redis.type(key) == "string"]
    await fake_redis.set(key, json.dumps({"latest_hour": "yesterday", "stations": {"44132": [35.69, 139.76]}, "hours": {}}))

    assert await load_station_rain_materials(now) is None
