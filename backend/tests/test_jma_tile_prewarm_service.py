import json

from app.services import jma_tile_prewarm_service as prewarm


class FakeJmaTileClient:
    """`JmaTileClient.get()`だけを実装したフェイク。targetTimes.jsonパスとタイル本体
    パスを区別せず、pathをキーに応答を切り替える。"""

    def __init__(self, target_times: dict[str, list[dict] | None], tile_result=(b"tile-bytes", "image/png")):
        self._target_times = target_times
        self._tile_result = tile_result
        self.requested_paths: list[str] = []

    async def get(self, path):
        self.requested_paths.append(path)
        if path in self._target_times:
            raw = self._target_times[path]
            if raw is None:
                return None
            return json.dumps(raw).encode("utf-8"), "application/json"
        return self._tile_result


def test_pick_current_entry_filters_by_element_and_picks_latest_basetime():
    raw = [
        {"basetime": "20260829170000", "validtime": "20260829170000", "member": "immed0", "elements": ["land", "inund"]},
        {"basetime": "20260829180000", "validtime": "20260829180000", "member": "immed0", "elements": ["land"]},
        {"basetime": "20260829180000", "validtime": "20260829180000", "member": "immed0", "elements": ["inund"]},
    ]

    entry = prewarm._pick_current_entry(raw, "land")

    assert entry is not None
    assert entry["basetime"] == "20260829180000"


def test_pick_current_entry_returns_none_when_element_not_found():
    raw = [{"basetime": "1", "validtime": "1", "member": "immed0", "elements": ["inund"]}]

    assert prewarm._pick_current_entry(raw, "flood") is None


def test_pick_current_entry_with_element_id_none_skips_filtering_and_prefers_observed():
    """element_id=None（絞り込み対象を指定しない汎用呼び出し）では、実況
    （validtime===basetime）のうち最新basetimeを選ぶ（予測フレームより実況を優先する、
    jmaNowcastFrames.ts: latestObservedFrameIndexと同じ考え方）。改善計画T514
    フォローアップ: 以前はnowcグループの呼び出し元がこのelement_id=Noneを常用していたが、
    それ自体が誤りだった（下記test_prewarm_jma_tiles_for_nowc_skips_liden_only_entry
    参照）。この関数自体の「element_id=Noneなら絞り込まない」という汎用的な挙動は
    引き続き正しいため、その挙動だけを検証する。"""
    raw = [
        {"basetime": "20260829170000", "validtime": "20260829170000"},  # 実況
        {"basetime": "20260829170000", "validtime": "20260829171000"},  # 予測(10分先)
        {"basetime": "20260829160000", "validtime": "20260829160000"},  # 古い実況
    ]

    entry = prewarm._pick_current_entry(raw, None)

    assert entry == {"basetime": "20260829170000", "validtime": "20260829170000"}


def test_pick_current_entry_returns_none_for_empty_input():
    assert prewarm._pick_current_entry([], "land") is None


def test_tile_paths_for_layer_builds_expected_path_format():
    layer = prewarm._PrewarmLayer("土砂", "risk", "land", "png", 4, "irrelevant")
    entry = {"basetime": "20260829170000", "validtime": "20260829170000", "member": "immed0"}

    paths = prewarm._tile_paths_for_layer(layer, entry)

    assert len(paths) > 0
    assert all(p.startswith("bosai/jmatile/data/risk/20260829170000/immed0/20260829170000/surf/land/") for p in paths)
    assert all(p.endswith(".png") for p in paths)


def test_tile_paths_for_layer_at_zoom4_covers_exactly_one_tile():
    """WIND_GRID_BBOX（関東本土）はzoom4では1タイルに収まる（改善計画T510の試算通り）。"""
    layer = prewarm._PrewarmLayer("test", "risk", "land", "png", 4, "irrelevant")
    entry = {"basetime": "1", "validtime": "1", "member": "immed0"}

    paths = prewarm._tile_paths_for_layer(layer, entry)

    assert len(paths) == 1


def test_tile_paths_for_layer_nowc_uses_literal_member_none():
    layer = prewarm._PrewarmLayer("test", "nowc", "thns", "png", 4, "irrelevant")
    entry = {"basetime": "1", "validtime": "1"}  # nowcのエントリはmemberフィールドを持たない

    paths = prewarm._tile_paths_for_layer(layer, entry)

    assert len(paths) == 1
    assert "/nowc/1/none/1/surf/thns/" in paths[0]


async def test_prewarm_jma_tiles_dedupes_shared_target_times_fetch(monkeypatch):
    risk_target_times = "bosai/jmatile/data/risk/targetTimes.json"
    monkeypatch.setattr(
        prewarm,
        "_LAYERS",
        (
            prewarm._PrewarmLayer("土砂", "risk", "land", "png", 4, risk_target_times),
            prewarm._PrewarmLayer("大雨", "risk", "rain_mesh", "png", 4, risk_target_times),
        ),
    )
    raw_entries = [
        {
            "basetime": "20260829170000",
            "validtime": "20260829170000",
            "member": "immed0",
            "elements": ["land", "rain_mesh"],
        }
    ]
    fake = FakeJmaTileClient({risk_target_times: raw_entries})

    await prewarm.prewarm_jma_tiles(fake)

    # targetTimes.jsonは1回だけfetch（2レイヤーが同じpathを共有するため重複フェッチしない）。
    target_times_requests = [p for p in fake.requested_paths if p == risk_target_times]
    assert len(target_times_requests) == 1
    # zoom4はWIND_GRID_BBOXで1タイルのため、2レイヤー分=2タイルフェッチされる。
    tile_requests = [p for p in fake.requested_paths if p != risk_target_times]
    assert len(tile_requests) == 2


async def test_prewarm_jma_tiles_skips_layer_when_target_times_fetch_fails(monkeypatch):
    risk_target_times = "bosai/jmatile/data/risk/targetTimes.json"
    monkeypatch.setattr(
        prewarm, "_LAYERS", (prewarm._PrewarmLayer("土砂", "risk", "land", "png", 4, risk_target_times),)
    )
    fake = FakeJmaTileClient({risk_target_times: None})

    await prewarm.prewarm_jma_tiles(fake)  # 例外を送出せず正常終了すること

    assert fake.requested_paths == [risk_target_times]


async def test_prewarm_jma_tiles_for_nowc_skips_liden_only_entry(monkeypatch):
    """改善計画T514フォローアップ: targetTimes_N3.jsonは5分おきにエントリを持つが、
    雷ナウキャスト(thns)自体は10分おきにしか更新されない。5分ズレたエントリは
    "elements": ["liden"]（雷放電位置データのみ）しか持たず、thnsのタイルが存在しない
    （実機のbackendログでこの5分ズレのbasetimeを使ったタイル取得がhttp_404になることを
    確認済み）。プリウォームがelementsで絞り込まず最新basetimeを無条件に採用すると、
    liden-onlyのbasetimeでタイルパスを組み立ててしまう——nowcグループも他グループと
    同じくelement_idで絞り込むべきことをこのテストで検証する。"""
    nowc_target_times = "bosai/jmatile/data/nowc/targetTimes_N3.json"
    monkeypatch.setattr(
        prewarm, "_LAYERS", (prewarm._PrewarmLayer("雷ナウキャスト", "nowc", "thns", "png", 4, nowc_target_times),)
    )
    raw_entries = [
        {"basetime": "20260831165000", "validtime": "20260831165000", "elements": ["thns", "trns"]},
        {"basetime": "20260831165500", "validtime": "20260831165500", "elements": ["liden"]},
    ]
    fake = FakeJmaTileClient({nowc_target_times: raw_entries})

    await prewarm.prewarm_jma_tiles(fake)

    tile_requests = [p for p in fake.requested_paths if p != nowc_target_times]
    assert len(tile_requests) > 0
    assert all("/nowc/20260831165000/" in p for p in tile_requests)
    assert not any("/nowc/20260831165500/" in p for p in tile_requests)


async def test_prewarm_jma_tiles_skips_layer_when_element_not_in_target_times(monkeypatch):
    risk_target_times = "bosai/jmatile/data/risk/targetTimes.json"
    monkeypatch.setattr(
        prewarm, "_LAYERS", (prewarm._PrewarmLayer("洪水", "risk", "flood", "pbf", 4, risk_target_times),)
    )
    raw_entries = [
        {"basetime": "1", "validtime": "1", "member": "immed0", "elements": ["land"]},  # floodを含まない
    ]
    fake = FakeJmaTileClient({risk_target_times: raw_entries})

    await prewarm.prewarm_jma_tiles(fake)

    assert fake.requested_paths == [risk_target_times]
