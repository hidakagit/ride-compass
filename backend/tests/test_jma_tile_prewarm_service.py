"""`services/jma_tile_prewarm_service.py`——気象庁タイルの定期プリウォーム（温めるフレームの選び方・
温めるタイル・在否インデックス）。

ここで見ないもの:
- タイル1枚の取得とRedisへの保存 → `JmaTileClient`（`infrastructure/jma_tile_client.py`のテスト）
- 空タイルの判定・タイルパスの解析 → `test_jma_tile_content.py`・`infrastructure/jma_tile_interpolation.py`のテスト
- 要素ごとのズームの仕様 → `test_jma_tile_specs.py`

配信元（`JmaTileClient`）と在否インデックスの保存（`set_index`）・空タイルの判定（`is_empty_tile`）は
代役へ差し替え、本物の署名へ当てる（`bound`）。温める範囲はテストが小さな矩形を与える。
要素は実在の配信要素id（降水ナウキャスト→降水短時間予報の2段・キキクルの洪水）の仕様を使う。
"""

import json
import logging

import pytest

from app.services import jma_tile_prewarm_service as service
from tests.bound_fake import bound

NOWCAST, SHORT_RANGE, FLOOD = "hrpns", "rasrf", "flood"


def _client_method(fake):
    return bound(getattr(service.JmaTileClient, fake.__name__), fake)


class Client:
    """配信元の代役。パスごとの応答を持ち、要求されたパスを残す。既定の応答はタイル1枚ぶんの中身。"""

    def __init__(self, responses: dict[str, object] | None = None, default: object = (b"tile", "image/png")):
        self.responses = dict(responses or {})
        self.default = default
        self.requested: list[str] = []

    @_client_method
    async def get(self, path):
        self.requested.append(path)
        return self.responses.get(path, self.default)


def _json(rows: list[dict]) -> tuple[bytes, str]:
    return json.dumps(rows).encode(), "application/json"


@pytest.fixture
def small_area(monkeypatch):
    area = service.BoundingBox(min_latitude=35.60, min_longitude=139.70, max_latitude=35.61, max_longitude=139.71)
    monkeypatch.setattr(service, "_PREWARM_BBOX", area)
    return area


@pytest.fixture
def stored(monkeypatch):
    payloads: list[dict] = []

    async def set_index(payload):
        payloads.append(payload)

    monkeypatch.setattr(service, "set_index", bound(service.set_index, set_index))
    return payloads


@pytest.fixture
def empty_marker(monkeypatch):
    """中身が`b"empty"`のタイルを空と判定する。"""
    monkeypatch.setattr(
        service, "is_empty_tile", bound(service.is_empty_tile, lambda content, extension: content == b"empty")
    )


# ---- 温める要素 ----


def test_an_element_without_a_spec_cannot_be_a_layer():
    with pytest.raises(KeyError):
        service._PrewarmLayer("x", "no_such_element")


@pytest.mark.parametrize(("element", "extension"), [(FLOOD, "pbf"), (NOWCAST, "png")])
def test_a_vector_element_is_warmed_as_pbf_and_a_raster_one_as_png(element, extension):
    assert service._PrewarmLayer("x", element).extension == extension


def test_layers_are_one_per_time_stage_of_each_tiled_element(monkeypatch):
    base = service.WEATHER_ELEMENTS[0]
    tiled = base._replace(label="降水", jma_elements=(NOWCAST, SHORT_RANGE))
    untiled = base._replace(label="風", jma_elements=())
    monkeypatch.setattr(service, "WEATHER_ELEMENTS", (tiled, untiled))
    monkeypatch.setattr(
        service,
        "weather_element_tile",
        bound(service.weather_element_tile, lambda element: object() if element.jma_elements else None),
    )

    layers = service._layers_from_weather_elements()

    assert [(layer.label, layer.element_id, layer.previous_stage) for layer in layers] == [
        ("降水", NOWCAST, None),
        ("降水", SHORT_RANGE, NOWCAST),
    ]


# ---- 温めるフレームの選び方 ----


def test_the_current_frame_is_the_latest_observation_of_the_element():
    rows = [
        {"basetime": "0900", "validtime": "0900", "elements": [NOWCAST]},
        {"basetime": "1000", "validtime": "1000", "elements": [NOWCAST]},
        {"basetime": "1000", "validtime": "1100", "elements": [NOWCAST]},  # 予測
        {"basetime": "1100", "validtime": "1100", "elements": ["other"]},  # この要素のタイルは無い
    ]

    assert service._pick_current_entry(rows, NOWCAST) == rows[1]


def test_without_an_observation_the_latest_run_is_taken():
    rows = [
        {"basetime": "0900", "validtime": "1000", "elements": [NOWCAST]},
        {"basetime": "1000", "validtime": "1100", "elements": [NOWCAST]},
    ]

    assert service._pick_current_entry(rows, NOWCAST) == rows[1]


def test_no_row_for_the_element_means_no_current_frame():
    assert (
        service._pick_current_entry([{"basetime": "1000", "validtime": "1000", "elements": ["other"]}], NOWCAST) is None
    )


def test_a_later_stage_starts_with_the_first_frame_after_the_previous_stage_of_the_latest_full_run():
    rows = [
        # 古い完全なラン
        {"basetime": "0600", "validtime": "0700", "member": "m", "elements": [SHORT_RANGE]},
        {"basetime": "0600", "validtime": "0800", "member": "m", "elements": [SHORT_RANGE]},
        # 最新の完全なラン
        {"basetime": "0900", "validtime": "1000", "member": "m", "elements": [SHORT_RANGE]},
        {"basetime": "0900", "validtime": "1100", "member": "m", "elements": [SHORT_RANGE]},
        {"basetime": "0900", "validtime": "1200", "member": "m", "elements": [SHORT_RANGE]},
        # 単発の中間ラン（validtimeが1つだけ）は画面が描かない
        {"basetime": "1000", "validtime": "1030", "member": "m", "elements": [SHORT_RANGE]},
    ]

    # 前の段の最後が10:00なら、それより後で最も近い11:00
    assert service._pick_stage_entry(rows, SHORT_RANGE, after="1000") == rows[3]


def test_a_later_stage_has_no_frame_when_nothing_comes_after_the_previous_stage():
    rows = [
        {"basetime": "0900", "validtime": "1000", "elements": [SHORT_RANGE]},
        {"basetime": "0900", "validtime": "1100", "elements": [SHORT_RANGE]},
    ]

    assert service._pick_stage_entry(rows, SHORT_RANGE, after="1100") is None


def test_a_later_stage_reads_only_the_rows_of_its_own_element():
    rows = [
        {"basetime": "0900", "validtime": "1000", "member": "m", "elements": [SHORT_RANGE]},
        {"basetime": "0900", "validtime": "1100", "member": "m", "elements": [SHORT_RANGE]},
        # 同じ時刻一覧に載る別の要素の、より新しい完全なラン
        {"basetime": "0930", "validtime": "1030", "member": "m", "elements": ["other"]},
        {"basetime": "0930", "validtime": "1130", "member": "m", "elements": ["other"]},
    ]

    assert service._pick_stage_entry(rows, SHORT_RANGE, after="1000") == rows[1]


def test_each_member_has_its_own_latest_full_run():
    rows = [
        {"basetime": "0900", "validtime": "1000", "member": "a", "elements": [SHORT_RANGE]},
        {"basetime": "0900", "validtime": "1200", "member": "a", "elements": [SHORT_RANGE]},
        # memberが違えば、より古いランでもそのmemberの最新の完全なラン
        {"basetime": "0600", "validtime": "1030", "member": "b", "elements": [SHORT_RANGE]},
        {"basetime": "0600", "validtime": "1100", "member": "b", "elements": [SHORT_RANGE]},
    ]

    assert service._pick_stage_entry(rows, SHORT_RANGE, after="1000") == rows[2]


# ---- 温めるタイル ----


def test_tiles_are_warmed_at_every_native_zoom_up_to_the_top_and_nowhere_else(small_area):
    layer = service._PrewarmLayer("x", FLOOD)

    paths = service._tile_paths_for_layer(layer, {"basetime": "B", "validtime": "V", "member": "m"})

    zooms = {int(p.split("/")[-3]) for p in paths}
    expected = {
        z
        for z in range(service._MIN_ZOOM, service.effective_max_zoom(layer.spec) + 1)
        if service.has_native_tile(layer.spec, z)
    }
    assert zooms == expected
    assert all(
        p.startswith(f"bosai/jmatile/data/{layer.group}/B/m/V/surf/{FLOOD}/") and p.endswith(".pbf") for p in paths
    )


def test_nowcast_paths_always_use_the_placeholder_member(small_area):
    layer = service._PrewarmLayer("x", NOWCAST)

    paths = service._tile_paths_for_layer(layer, {"basetime": "B", "validtime": "V", "member": "m"})

    assert paths and all("/B/none/V/" in p for p in paths)


# ---- 在否インデックス ----


def test_zooms_filled_by_interpolation_are_listed_from_their_parents():
    # 偶数ズームだけに実データがある要素: 奇数ズームは親（1つ上の偶数）の中身ありタイルの4象限
    zooms = service._with_interpolated_zooms(NOWCAST, {4: [[3, 5]]})

    assert zooms[5] == [[6, 10], [6, 11], [7, 10], [7, 11]]
    assert 6 not in zooms  # 実データのあるズームは温めた結果だけが持つ


def test_a_zoom_whose_parent_has_nothing_stays_unlisted():
    assert service._with_interpolated_zooms(NOWCAST, {4: [], 6: [[1, 1]]}) == {
        4: [],
        6: [[1, 1]],
        7: [[2, 2], [2, 3], [3, 2], [3, 3]],
    }


def test_no_present_tiles_means_no_zooms():
    assert service._with_interpolated_zooms(NOWCAST, {}) == {}


async def test_the_index_carries_the_coverage_and_each_elements_frame(small_area, stored):
    await service._store_index({NOWCAST: {"basetime": "B", "validtime": "V"}}, {NOWCAST: {4: [[3, 5]]}})

    (payload,) = stored
    assert payload["coverage"] == {
        "min_longitude": small_area.min_longitude,
        "min_latitude": small_area.min_latitude,
        "max_longitude": small_area.max_longitude,
        "max_latitude": small_area.max_latitude,
    }
    element = payload["elements"][NOWCAST]
    assert (element["basetime"], element["validtime"], element["member"]) == ("B", "V", "none")
    # JSONの往復で型が変わらないよう、ズームは文字列のキー
    assert set(element["zooms"]) == {"4", "5"}


async def test_an_element_with_nothing_to_draw_is_still_listed_with_its_frame(small_area, stored):
    # 平常時の大半。クライアントはフレームが一致するかを見るため、座標が空でも要素ごと載る
    await service._store_index({NOWCAST: {"basetime": "B", "validtime": "V"}}, {})

    (payload,) = stored
    element = payload["elements"][NOWCAST]
    assert (element["basetime"], element["validtime"], element["zooms"]) == ("B", "V", {})


async def test_no_frames_means_no_index(stored):
    await service._store_index({}, {})

    assert stored == []


# ---- 時刻一覧の取得 ----


@pytest.mark.parametrize(
    "response",
    [None, service.EmptyTile(), (b"not json", "application/json")],
)
async def test_an_unreadable_time_list_is_nothing(response):
    assert await service._fetch_target_times(Client({"t.json": response}), "t.json") is None


async def test_a_time_list_is_read_as_json():
    rows = [{"basetime": "B"}]

    assert await service._fetch_target_times(Client({"t.json": _json(rows)}), "t.json") == rows


# ---- 一巡 ----


@pytest.fixture
def two_stages(monkeypatch):
    layers = (service._PrewarmLayer("降水", NOWCAST), service._PrewarmLayer("降水", SHORT_RANGE, NOWCAST))
    monkeypatch.setattr(service, "_LAYERS", layers)
    return layers


def _times(layers, nowcast_rows: list[dict], short_rows: list[dict]) -> dict[str, object]:
    nowcast, short_range = layers
    responses: dict[str, object] = {path: _json([]) for path in nowcast.target_times_paths}
    responses[nowcast.target_times_paths[0]] = _json(nowcast_rows)
    for path in short_range.target_times_paths:
        responses[path] = _json(short_rows)
    return responses


NOWCAST_ROWS = [{"basetime": "1000", "validtime": "1000", "elements": [NOWCAST]}]
SHORT_ROWS = [
    {"basetime": "0900", "validtime": "1000", "member": "m", "elements": [SHORT_RANGE]},
    {"basetime": "0900", "validtime": "1100", "member": "m", "elements": [SHORT_RANGE]},
]


async def test_a_round_warms_each_stage_and_stores_what_was_found(small_area, stored, empty_marker, two_stages):
    client = Client(_times(two_stages, NOWCAST_ROWS, SHORT_ROWS))

    await service.prewarm_jma_tiles(client)

    tiles = [p for p in client.requested if "/surf/" in p]
    assert {p.split("/surf/")[1].split("/")[0] for p in tiles} == {NOWCAST, SHORT_RANGE}
    # 後の段は前の段の最後（10:00）より後のフレーム
    assert all("/0900/m/1100/" in p for p in tiles if f"/{SHORT_RANGE}/" in p)
    (payload,) = stored
    assert set(payload["elements"]) == {NOWCAST, SHORT_RANGE}


async def test_each_time_list_is_fetched_once_per_round(small_area, stored, empty_marker, monkeypatch):
    shared = service._PrewarmLayer("a", NOWCAST)
    monkeypatch.setattr(service, "_LAYERS", (shared, service._PrewarmLayer("b", NOWCAST)))
    client = Client({path: _json(NOWCAST_ROWS) for path in shared.target_times_paths})

    await service.prewarm_jma_tiles(client)

    for path in shared.target_times_paths:
        assert client.requested.count(path) == 1


async def test_the_stage_boundary_is_the_last_frame_of_the_previous_element_itself(
    small_area, stored, empty_marker, two_stages
):
    nowcast_rows = [
        {"basetime": "1000", "validtime": "1000", "elements": [NOWCAST]},
        # 同じ時刻一覧に載る別の要素の、より先のフレーム
        {"basetime": "1000", "validtime": "1100", "elements": ["other"]},
    ]
    short_rows = [
        {"basetime": "0900", "validtime": "1030", "member": "m", "elements": [SHORT_RANGE]},
        {"basetime": "0900", "validtime": "1130", "member": "m", "elements": [SHORT_RANGE]},
    ]
    client = Client(_times(two_stages, nowcast_rows, short_rows))

    await service.prewarm_jma_tiles(client)

    short_tiles = [p for p in client.requested if f"/surf/{SHORT_RANGE}/" in p]
    assert short_tiles and all("/0900/m/1030/" in p for p in short_tiles)


async def test_a_later_stage_is_skipped_when_the_previous_stage_has_no_rows(
    small_area, stored, empty_marker, two_stages, caplog
):
    client = Client(_times(two_stages, [], SHORT_ROWS))

    with caplog.at_level(logging.WARNING, logger=service.logger.name):
        await service.prewarm_jma_tiles(client)

    # 段の境目が分からないので、後の段も温めない
    assert [p for p in client.requested if "/surf/" in p] == []
    warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any(NOWCAST in m and SHORT_RANGE in m for m in warnings)
    assert stored == []


async def test_only_tiles_with_something_to_draw_enter_the_index(small_area, stored, empty_marker, two_stages):
    responses = _times(two_stages, NOWCAST_ROWS, [])
    client = Client(responses)
    await service.prewarm_jma_tiles(client)
    tiles = [p for p in client.requested if "/surf/" in p]
    assert len(tiles) >= 3, "温めるタイルが足りず、4通りの応答を配れない"

    # 1枚目は中身あり、2枚目は取得失敗、3枚目は空と確認済み、残りは空の中身
    outcomes = [(b"tile", "image/png"), None, service.EmptyTile()]
    for path, outcome in zip(tiles, outcomes):
        responses[path] = outcome
    client = Client(responses, default=(b"empty", "image/png"))
    stored.clear()

    await service.prewarm_jma_tiles(client)

    zooms = stored[0]["elements"][NOWCAST]["zooms"]
    listed = [
        tuple(xy)
        for z, coords in zooms.items()
        for xy in coords
        if service.has_native_tile(service.JMA_TILE_SPECS[NOWCAST], int(z))
    ]
    first = tiles[0].split("/surf/")[1].split("/")
    assert listed == [(int(first[2]), int(first[3].split(".")[0]))]
