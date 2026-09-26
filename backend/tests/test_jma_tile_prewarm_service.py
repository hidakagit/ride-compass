"""`services/jma_tile_prewarm_service.py`——気象庁の動的タイルを定期的に温め、在否インデックスを残す。

確かめるのは公開の入口`prewarm_jma_tiles`から見える振る舞いだけ: 配信元へ何を取りに行くか（時刻一覧と
タイルのパス）と、保存する在否インデックス、取れなかったときの警告。温める要素・範囲・ズームは本物の宣言
（動的気象の要素・配信元仕様・運用範囲）をそのまま通す。

差し替えるのは、注入される配信元のクライアント（`JmaTileClient.get`の1メソッド。本物の署名に当てる）と、
インデックスの書き込み先（Redis）だけ。

ここで見ないもの:
- タイルの取得・キャッシュ・空タイルの扱い → `test_jma_tile_client.py`・`test_jma_tile_redis_cache.py`
- 空かどうかの判定 → `test_jma_tile_content.py`
- 配信元仕様（ズームの偶奇・時刻一覧のファイル） → `test_jma_tile_specs.py`

配信元の仕様の事実として、要素はどれも偶数ズーム（4・6・8・10、雷と竜巻は8まで）だけが実データを持ち、
奇数ズームは親から補う。
"""

import io
import json
import logging

import pytest
from PIL import Image

from app.infrastructure.jma_tile_client import JmaTileClient
from app.services import jma_tile_prewarm_service as prewarm
from tests.bound_fake import bound

N1 = "bosai/jmatile/data/nowc/targetTimes_N1.json"
N2 = "bosai/jmatile/data/nowc/targetTimes_N2.json"
N3 = "bosai/jmatile/data/nowc/targetTimes_N3.json"
RASRF = "bosai/jmatile/data/rasrf/targetTimes.json"
RISK = "bosai/jmatile/data/risk/targetTimes.json"
TARGET_TIMES = {N1, N2, N3, RASRF, RISK}
RISK_ELEMENTS = ["rain_mesh", "land", "inund", "flood"]


def _row(basetime, validtime, *elements, **extra):
    return {"basetime": basetime, "validtime": validtime, "elements": list(elements), **extra}


def _target_times():
    return {
        # 降水の1段目（実況＋予測）。1段目の最後のvalidtimeは01:00。
        N1: [_row("20260922001000", "20260922001000", "hrpns"), _row("20260922001000", "20260922003000", "hrpns")],
        # 別の要素の行は、1段目の境目にも2段目の選び方にも入れない（入れると境目が02:30へずれる）。
        N2: [_row("20260922001000", "20260922010000", "hrpns"), _row("20260922001000", "20260922023000", "other")],
        # 雷・竜巻。より新しい行が別の要素だけを載せている（その要素のタイルは無い）。
        N3: [
            _row("20260922000000", "20260922000000", "thns", "trns"),
            _row("20260922000500", "20260922000500", "thns", "trns"),
            _row("20260922002000", "20260922002000", "other"),
        ],
        RASRF: [
            # 線状降水帯予測は予測フレームしか持たない。
            _row("20260921230000", "20260922010000", "sjfcstmap"),
            _row("20260922000000", "20260922020000", "sjfcstmap"),
            # 降水の2段目。最新の完全な予報ラン（00:00、validtimeが複数）の、01:00より後の最初のフレームを描く。
            _row("20260922000000", "20260922003000", "rasrf", member="m1"),
            _row("20260922000000", "20260922030000", "rasrf", member="m1"),
            _row("20260922000000", "20260922020000", "rasrf", member="m1"),
            # 同じランの別の要素の行（入れると01:30を選んでしまう）。
            _row("20260922000000", "20260922013000", "other", member="m1"),
            # 単発の中間ラン（validtime==basetime、1件だけ）は画面が描かない。
            _row("20260922003000", "20260922030000", "rasrf", member="m1"),
            # 古い完全なラン。
            _row("20260921230000", "20260922013000", "rasrf", member="m1"),
            _row("20260921230000", "20260922023000", "rasrf", member="m1"),
        ],
        RISK: [
            _row("20260921235000", "20260921235000", *RISK_ELEMENTS),
            _row("20260922000000", "20260922000000", *RISK_ELEMENTS),
            _row("20260922000000", "20260922010000", *RISK_ELEMENTS),
        ],
    }


def _png(alpha: int) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", (2, 2), (255, 0, 0, alpha)).save(buffer, format="PNG")
    return buffer.getvalue()


OPAQUE, TRANSPARENT = _png(255), _png(0)


class Source:
    """配信元の代役。時刻一覧はJSONで、タイルは`tiles`（パスの一部→返す値）の最初に当たるもの、無ければ空タイル。"""

    def __init__(self, target_times=None, tiles=None):
        self.target_times = _target_times() if target_times is None else target_times
        self.tiles = tiles or {}
        self.requests: list[str] = []

    async def get(self, path):
        self.requests.append(path)
        if path in TARGET_TIMES:
            value = self.target_times.get(path)
            if value is None or isinstance(value, prewarm.EmptyTile):
                return value
            if isinstance(value, bytes):
                return value, "text/html"
            return json.dumps(value).encode(), "application/json"
        for fragment, value in self.tiles.items():
            if fragment in path:
                return value
        return prewarm.EmptyTile()

    get = bound(JmaTileClient.get, get)

    def tile_requests(self, element):
        return [p for p in self.requests if f"/surf/{element}/" in p]


def _tile_parts(path):
    """`.../{group}/{basetime}/{member}/{validtime}/surf/{element}/{z}/{x}/{y}.{ext}`を分ける。"""
    group, basetime, member, validtime, _surf, element, z, x, rest = path.split("/")[3:]
    y, ext = rest.split(".")
    return {"group": group, "basetime": basetime, "member": member, "validtime": validtime,
            "element": element, "z": int(z), "x": int(x), "y": int(y), "ext": ext}


@pytest.fixture
def stored(monkeypatch):
    """インデックスの書き込み先（Redis）。書かれたペイロードを並べる。"""
    payloads: list[dict] = []

    async def set_index(payload):
        payloads.append(payload)

    monkeypatch.setattr(prewarm, "set_index", set_index)
    return payloads


async def _run(source):
    await prewarm.prewarm_jma_tiles(source)


# --- 取りに行くもの ---


async def test_each_time_list_is_fetched_once_even_when_several_elements_share_it(stored):
    source = Source()

    await _run(source)

    target_times_requests = [p for p in source.requests if p in TARGET_TIMES]
    assert sorted(target_times_requests) == sorted(TARGET_TIMES)


async def test_tiles_are_fetched_at_the_zooms_the_source_has_data_for(stored):
    source = Source()

    await _run(source)

    assert {_tile_parts(p)["z"] for p in source.tile_requests("rain_mesh")} == {4, 6, 8, 10}
    assert {_tile_parts(p)["z"] for p in source.tile_requests("thns")} == {4, 6, 8}


async def test_an_element_with_observations_and_forecasts_warms_the_latest_observation(stored):
    """実況＋予測の要素は、画面の時系列の左端（最新の実況）を温める。予測フレームは温めない（全フレームだと
    タイル数が桁違いになる）。"""
    source = Source()

    await _run(source)

    frames = {(_tile_parts(p)["basetime"], _tile_parts(p)["validtime"]) for p in source.tile_requests("hrpns")}
    assert frames == {("20260922001000", "20260922001000")}


async def test_an_element_that_holds_one_current_value_warms_its_newest_row_even_when_it_is_a_forecast(stored):
    """配信元が実況と予測を統合済みの「現在」の単一値は、画面が最新の行を描く。実況の行を優先すると、画面と
    違うフレームを温め、在否インデックスも画面のフレームと一致しなくなる。"""
    target_times = _target_times()
    target_times[RISK] += [_row("20260922001000", "20260922013000", *RISK_ELEMENTS)]
    source = Source(target_times=target_times)

    await _run(source)

    frames = {(_tile_parts(p)["basetime"], _tile_parts(p)["validtime"], _tile_parts(p)["member"])
              for p in source.tile_requests("rain_mesh")}
    assert frames == {("20260922001000", "20260922013000", "none")}
    assert stored[0]["elements"]["rain_mesh"]["validtime"] == "20260922013000"


async def test_rows_that_do_not_list_the_element_are_ignored(stored):
    """時刻一覧には、その要素のタイルが無い時刻の行も載る。それを採ると存在しないタイルを取りに行き続ける。"""
    source = Source()

    await _run(source)

    frames = {(_tile_parts(p)["basetime"], _tile_parts(p)["member"]) for p in source.tile_requests("thns")}
    assert frames == {("20260922000500", "none")}


async def test_an_element_with_only_forecast_frames_warms_its_latest_run(stored):
    source = Source()

    await _run(source)

    frames = {(_tile_parts(p)["basetime"], _tile_parts(p)["validtime"]) for p in source.tile_requests("sjfcstmap")}
    assert frames == {("20260922000000", "20260922020000")}


async def test_a_later_stage_warms_the_first_frame_the_screen_draws_after_the_earlier_stage(stored):
    """降水は01:00まで1段目、その先を2段目で描く。2段目は最新の完全な予報ランの、01:00より後の最初のフレーム。"""
    source = Source()

    await _run(source)

    frames = {(_tile_parts(p)["basetime"], _tile_parts(p)["validtime"], _tile_parts(p)["member"])
              for p in source.tile_requests("rasrf")}
    assert frames == {("20260922000000", "20260922020000", "m1")}


async def test_vector_tiles_are_requested_as_pbf(stored):
    source = Source()

    await _run(source)

    assert {_tile_parts(p)["ext"] for p in source.tile_requests("flood")} == {"pbf"}
    assert {_tile_parts(p)["ext"] for p in source.tile_requests("land")} == {"png"}


# --- 在否インデックス ---


async def test_the_index_lists_the_tiles_that_have_something_to_draw(stored):
    """中身のあるタイルだけを載せる。空タイル・透明な画像・0バイトのベクタ・取れなかったタイルは載せない。"""
    source = Source(tiles={
        "/surf/rain_mesh/4/": (OPAQUE, "image/png"),
        "/surf/rain_mesh/6/": (TRANSPARENT, "image/png"),
        "/surf/flood/4/": (b"", "application/x-protobuf"),
        "/surf/land/4/": None,
    })

    await _run(source)

    (payload,) = stored
    rain_mesh = payload["elements"]["rain_mesh"]
    z4 = sorted([_tile_parts(p)["x"], _tile_parts(p)["y"]] for p in source.tile_requests("rain_mesh")
                if _tile_parts(p)["z"] == 4)
    assert sorted(rain_mesh["zooms"]["4"]) == z4
    assert "6" not in rain_mesh["zooms"]
    assert payload["elements"]["flood"]["zooms"] == {}
    assert payload["elements"]["land"]["zooms"] == {}


async def test_a_zoom_filled_from_its_parent_is_listed_wherever_the_parent_has_something(stored):
    """補間で埋めるズームを載せないと、クライアントはそこを空と見なして取りに来ず、補間が一度も動かない。"""
    source = Source(tiles={"/surf/rain_mesh/4/": (OPAQUE, "image/png")})

    await _run(source)

    zooms = stored[0]["elements"]["rain_mesh"]["zooms"]
    expected = sorted([x * 2 + dx, y * 2 + dy] for x, y in zooms["4"] for dx in (0, 1) for dy in (0, 1))
    assert sorted(zooms["5"]) == expected
    assert "7" not in zooms  # 親の6に中身が無い


async def test_the_index_says_which_frame_and_which_area_it_describes(stored):
    """クライアントは自分が描くフレームと一致する要素だけを信用し、範囲の外は従来どおり取りに行く。"""
    await _run(Source())

    (payload,) = stored
    assert set(payload["elements"]) == {"hrpns", "rasrf", "sjfcstmap", "rain_mesh", "land", "inund", "thns", "trns", "flood"}
    assert payload["elements"]["rasrf"] | {"zooms": None} == {
        "basetime": "20260922000000", "validtime": "20260922020000", "member": "m1", "zooms": None,
    }
    coverage = payload["coverage"]
    assert coverage["min_longitude"] < coverage["max_longitude"]
    assert coverage["min_latitude"] < coverage["max_latitude"]


# --- 時刻一覧が取れないとき ---


@pytest.mark.parametrize("unusable", [None, prewarm.EmptyTile(), b"<html>maintenance</html>"])
async def test_elements_whose_time_list_cannot_be_read_are_skipped_with_a_warning(stored, caplog, unusable):
    target_times = _target_times()
    target_times[RISK] = unusable
    source = Source(target_times=target_times)

    with caplog.at_level(logging.WARNING, logger="ridecompass.jma_tile_prewarm_service"):
        await _run(source)

    assert not any(source.tile_requests(element) for element in RISK_ELEMENTS)
    assert set(stored[0]["elements"]).isdisjoint(RISK_ELEMENTS)
    assert source.tile_requests("thns")
    warning = next(r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)
    assert all(element in warning for element in RISK_ELEMENTS)


async def test_a_later_stage_starts_the_timeline_when_the_earlier_stage_has_no_frames(stored):
    """1段目が取れなければ、画面は2段目を最初から描く。温めるのもその最初のフレーム。"""
    target_times = _target_times()
    target_times[N1] = target_times[N2] = None

    source = Source(target_times=target_times)
    await _run(source)

    assert not source.tile_requests("hrpns")
    frames = {(_tile_parts(p)["basetime"], _tile_parts(p)["validtime"], _tile_parts(p)["member"])
              for p in source.tile_requests("rasrf")}
    assert frames == {("20260922000000", "20260922003000", "m1")}


async def test_nothing_is_stored_when_no_time_list_can_be_read(stored):
    """空のインデックスを書くと、クライアントは全タイルを空と見なして何も描かなくなる。"""
    source = Source(target_times={})

    await _run(source)

    assert stored == []
    assert [p for p in source.requests if p not in TARGET_TIMES] == []


async def test_a_later_stage_with_no_frame_after_the_earlier_stage_is_skipped(stored):
    """2段目の予報が1段目の終わりまでしか届いていなければ、画面はその段を描かない。"""
    target_times = _target_times()
    target_times[RASRF] = [row for row in target_times[RASRF] if "rasrf" not in row["elements"]] + [
        _row("20260922000000", "20260922003000", "rasrf", member="m1"),
        _row("20260922000000", "20260922010000", "rasrf", member="m1"),
    ]
    source = Source(target_times=target_times)

    await _run(source)

    assert not source.tile_requests("rasrf")
    assert source.tile_requests("hrpns")


async def test_each_member_of_a_later_stage_takes_its_own_latest_full_run(stored):
    """最新の完全なランはメンバーごとに決まる。全体で最新のランだけを見ると、別のメンバーの先に描くフレームを落とす。"""
    target_times = _target_times()
    target_times[RASRF] += [
        _row("20260921233000", "20260922015000", "rasrf", member="m2"),
        _row("20260921233000", "20260922025000", "rasrf", member="m2"),
    ]
    source = Source(target_times=target_times)

    await _run(source)

    frames = {(_tile_parts(p)["basetime"], _tile_parts(p)["validtime"], _tile_parts(p)["member"])
              for p in source.tile_requests("rasrf")}
    assert frames == {("20260921233000", "20260922015000", "m2")}
