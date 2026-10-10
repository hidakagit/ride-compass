"""jma_amedas_service.pyのテスト。

差し替えるのはプロセス境界だけ——気象庁への取得は応答の形のままURLごとに返すrespxの経路
（アメダスのJSONと推計気象分布の時刻一覧・タイルのPNG）、Redisはfakeredis（`fake_redis`）。
応答の形を解くクライアントは本物を通す。

JMAの観測値エンドポイントは1地点だけを絞り込めず全国分を1レスポンスで返すため、取得は
`refresh_all_stations`（main.pyの定期バッチが呼ぶ）が一括で担い、`get_nearest_observation`
（リクエスト経路）はRedis読み取り専用である。推計気象分布の色を取って区分へ読み替えるクライアントと、
観測値と雨の履歴の置き場は、自分のテストを持たないのでここで入口から通す。

ここで見ないもの:
- 実測と空から天気コードを導く規則 → `test_weather_domain.py`
- 風向コード・体感温度 → `test_jma_amedas.py`
- 気象庁の応答を解くこと → `test_jma_amedas_client.py`
- 1時間雨量の履歴から窓の累計・止んでからの時間を求めること → `test_rain.py`
"""

import io
import json
from datetime import datetime, timedelta

import httpx
import numpy as np
import pytest
import respx
from PIL import Image

from app.domain.jma_amedas import apparent_temperature_from_amedas
from app.domain.rain import HOURS_SINCE_RAIN, RAIN_HISTORY_HOURS, RAIN_HISTORY_MAX_AGE, rain_window_material_id
from app.domain.route import Coordinates
from app.domain.time_zone import JST
from app.infrastructure import jma_amedas_client, jma_tile_client
from app.infrastructure.debug_log import get_stats
from app.infrastructure.jma_amedas_client import new_latest_time_cache, new_station_table_cache
from app.infrastructure.jma_tile_client import JmaTileClient, JmaTileSharedState
from app.services.jma_amedas_service import JmaAmedasService, load_station_rain_materials, new_rain_materials_cache
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
    target_times = upstream.get(f"{SUIKEI_ROOT}/targetTimes.json")
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


def _service(http_client: httpx.AsyncClient) -> JmaAmedasService:
    """取得のキャッシュ（観測所マスタ・最新時刻・推計気象分布の時刻一覧）は、組み立てるたびに空から始まる。"""
    return JmaAmedasService(
        http_client,
        JmaTileClient(http_client, JmaTileSharedState()),
        station_table_cache=new_station_table_cache(),
        latest_time_cache=new_latest_time_cache(),
    )


#: 観測値と雨の履歴はRedisに置くので、どのテストも空のRedisから始める。
pytestmark = pytest.mark.usefixtures("fake_redis")


@pytest.mark.parametrize(
    ("answers", "message"),
    [
        ({"stations": None}, "観測所マスタ"),
        ({"latest_time": None}, "最新観測時刻"),
        ({"observation_map": lambda timestamp: None}, "観測値マップ"),
    ],
)
async def test_refresh_all_stations_warns_when_a_fetch_fails(caplog, answers, message):
    """呼び出し元は例外の有無しか見ないため、1件も書けていないことはサービス層自身がWARNINGで残すしかない。"""
    service = _service(_upstream(**answers))

    with caplog.at_level("WARNING", logger="ridecompass.jma_amedas_service"):
        count = await service.refresh_all_stations()

    assert count == 0
    assert any(message in record.message for record in caplog.records)


async def test_get_nearest_observation_reads_from_redis_without_fetching():
    upstream = _router()
    service = _service(client_for(upstream))
    # バッチ（定期実行想定）が先に全国分をキャッシュ済みという前提を再現する。
    await service.refresh_all_stations()
    upstream.reset()

    result = await service.get_nearest_observation(POINT)

    # 観測所マスタはクライアントのキャッシュから引き、観測値は気象庁へ取りに行かない（取りに行くのは推計気象分布だけ）。
    assert upstream.calls
    assert all(str(call.request.url).startswith(SUIKEI_ROOT) for call in upstream.calls)
    assert result is not None
    # 観測所名と観測の時刻は、バッチが取った観測所の表と最新の観測時刻のもの。
    assert result.station_name == "東京"
    assert result.observed_at == datetime.fromisoformat(LATEST_TIME)
    assert result.temperature_c == 26.5
    assert result.apparent_temperature_c == apparent_temperature_from_amedas(26.5, 70, 3.5)
    assert result.wind_speed_ms == 3.5
    assert result.wind_direction is not None and result.wind_direction.label == "南"
    assert result.precipitation_10min_mm == 0.0
    # 日の出・日没はRedisには無く、クエリ地点に対してその場で計算される。
    assert result.twilight is not None


async def test_observation_reads_and_writes_are_counted_in_the_stats():
    """置き場の不調は`/api/debug/stats`で見る。集計に載らないと、Redisが落ちても観測値が出ないだけで気づけない。"""
    category = "cache:jma-amedas-redis"
    before = get_stats().external.get(category)
    service = _service(_upstream())

    await service.refresh_all_stations()
    await service.get_nearest_observation(POINT)

    after = get_stats().external[category]
    assert after.calls - (before.calls if before else 0) == 2
    assert after.cache_hits - (before.cache_hits if before else 0) == 1


async def _nearest(**answers):
    service = _service(_upstream(**answers))
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
        (0.0, CLEAR, 0),  # 晴れた夜は、日照が0でも晴れ。地点の周りはくもりで塗ってある
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


async def test_get_nearest_observation_returns_none_when_not_yet_cached():
    service = _service(_upstream())

    # refresh_all_stationsを呼んでいない（＝定期バッチがまだ一度も成功していない）状態。
    result = await service.get_nearest_observation(POINT)

    assert result is None


# --- 毎正時の1時間雨量の履歴（雨の材料の元） ---


def _latest_hour(now: datetime) -> datetime:
    """直近の完全な正時の1つ前。観測時刻は正時の50分に置き、正時の地図JSONを別に取りに行かせる。"""
    return now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)


class RainMaps:
    """正時ごとの地図JSON。東京（44132）だけが雨量計を持ち、`rain_by_back`（何時間前の正時→mm）の雨を返す。
    `broken_by_back`（何時間前の正時→応答）の正時は、雨の代わりにその応答を返す（Noneは取れない）。"""

    def __init__(self, latest_hour: datetime, rain_by_back: dict[int, float], broken_by_back: dict[int, dict | None] = {}):
        self.latest_hour = latest_hour
        self.rain_by_back = rain_by_back
        self.broken_by_back = broken_by_back
        self.requested_hours: list[int] = []

    def observation_map(self, timestamp):
        at = datetime.strptime(timestamp, "%Y%m%d%H%M%S").replace(tzinfo=JST)
        if at.minute != 0:
            return OBSERVATION_MAP
        back = int((self.latest_hour - at) / timedelta(hours=1))
        self.requested_hours.append(back)
        if back in self.broken_by_back:
            return self.broken_by_back[back]
        rain = self.rain_by_back.get(back, 0.0)
        return {**OBSERVATION_MAP, "44132": {**OBSERVATION_MAP["44132"], "precipitation1h": [rain, 0]}}


def _rain_service(maps: RainMaps) -> JmaAmedasService:
    latest_time = (maps.latest_hour + timedelta(minutes=50)).isoformat()
    return _service(_upstream(latest_time=latest_time, observation_map=maps.observation_map))


async def test_rain_history_is_backfilled_from_past_hourly_maps():
    now = datetime.now(JST)
    maps = RainMaps(_latest_hour(now), rain_by_back={2: 3.0, 3: 3.0})

    await _rain_service(maps).refresh_all_stations()
    materials = await load_station_rain_materials(now, new_rain_materials_cache())

    assert sorted(maps.requested_hours) == list(range(RAIN_HISTORY_HOURS))
    assert materials is not None
    # 雨量計を持たない観測所（99999）は最寄りの候補に入らない。
    assert len(materials.latitudes) == 1
    assert materials.values[rain_window_material_id(3)][0] == 3.0
    assert materials.values[HOURS_SINCE_RAIN][0] == 2.0


async def test_rain_history_fetches_only_hours_it_does_not_have():
    now = datetime.now(JST)
    latest_hour = _latest_hour(now)
    earlier = RainMaps(latest_hour - timedelta(hours=1), rain_by_back={})
    await _rain_service(earlier).refresh_all_stations()

    later = RainMaps(latest_hour, rain_by_back={0: 1.5})
    await _rain_service(later).refresh_all_stations()
    materials = await load_station_rain_materials(now, new_rain_materials_cache())

    assert later.requested_hours == [0]
    assert materials is not None
    assert materials.values[rain_window_material_id(1)][0] == 1.5


@pytest.mark.parametrize(
    "broken",
    [
        None,
        OBSERVATION_MAP,
        {**OBSERVATION_MAP, "44132": {**OBSERVATION_MAP["44132"], "precipitation1h": [None, 1]}},
    ],
    ids=["not fetched", "no rain gauge reports", "every rain gauge is missing"],
)
async def test_an_hour_that_could_not_be_fetched_is_retried_and_leaves_its_windows_empty_meanwhile(broken):
    """取れても1時間雨量の値が1つも無い正時を取れたとして残すと、二度と取り直さず、その正時を含む窓が全国で
    値を持たないまま、窓から外れるまで戻らない。"""
    now = datetime.now(JST)
    latest_hour = _latest_hour(now)
    failing = RainMaps(latest_hour, rain_by_back={}, broken_by_back={5: broken})
    await _rain_service(failing).refresh_all_stations()
    materials = await load_station_rain_materials(now, new_rain_materials_cache())

    assert materials is not None
    assert materials.values[rain_window_material_id(4)][0] == 0.0
    assert np.isnan(materials.values[rain_window_material_id(6)][0])

    retry = RainMaps(latest_hour, rain_by_back={})
    await _rain_service(retry).refresh_all_stations()

    assert retry.requested_hours == [5]


async def test_rain_history_is_not_refetched_while_redis_is_down(redis_server):
    """置き場が使えないたびに全本を取り直すと、10分ごとに気象庁へ全本を問い合わせ続ける。観測値の書き込みだけを
    飛ばし、バッチは取れた観測所の数を返して終わる。"""
    redis_server.connected = False
    maps = RainMaps(_latest_hour(datetime.now(JST)), rain_by_back={})

    assert await _rain_service(maps).refresh_all_stations() == 2
    assert maps.requested_hours == []


async def test_rain_materials_are_not_served_from_a_stale_history():
    now = datetime.now(JST)
    maps = RainMaps(_latest_hour(now), rain_by_back={})
    await _rain_service(maps).refresh_all_stations()

    cache = new_rain_materials_cache()

    assert await load_station_rain_materials(now, cache) is not None
    assert await load_station_rain_materials(maps.latest_hour + RAIN_HISTORY_MAX_AGE + timedelta(minutes=1), cache) is None


@pytest.mark.parametrize("unreadable", ["latest_hour", "rainfall"])
async def test_a_rain_history_stored_in_a_shape_that_cannot_be_read_serves_no_materials(fake_redis, unreadable):
    """保存した形は過去のコードが書いたもの。読めないまま展開すると、地図とルートの生成が500で落ちる。"""
    now = datetime.now(JST)
    await _rain_service(RainMaps(_latest_hour(now), rain_by_back={})).refresh_all_stations()
    (key,) = [key for key in await fake_redis.keys() if await fake_redis.type(key) == b"string"]
    stored = json.loads(await fake_redis.get(key))
    if unreadable == "latest_hour":
        stored["latest_hour"] = "yesterday"
    else:
        stored["hours"] = {stored["latest_hour"]: {station: "大雨" for station in stored["stations"]}}
    await fake_redis.set(key, json.dumps(stored))

    assert await load_station_rain_materials(now, new_rain_materials_cache()) is None
