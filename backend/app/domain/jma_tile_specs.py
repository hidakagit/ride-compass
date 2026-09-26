"""気象庁タイル配信の要素ごとの仕様レジストリ（パスの系統・ズーム・ベクタのレイヤー名・時刻一覧の在り処と
読み方）と、その読み方で時刻一覧の行をコマにする関数。

配信元（気象庁の各`*.properties__<hash>.xml`）は要素ごとに`zoomUse`（使用するズームの
偶奇）と`maxNativeZoom`（XML中のコメントで「画像が実在する最大ズームレベル」と説明されて
いる値）を持つ。アプリがタイルを要求してよい最大ズームはこの2つの組み合わせで決まり、
どちらか一方だけを見ると実データの無いズームを指してしまう。

MapLibreの`maxzoom`（frontendへは`domain/weather_elements.py: WEATHER_ELEMENTS`の生成物
`mapDisplay.weatherElements`経由で届く）とプリウォームバッチの対象ズーム
（`services/jma_tile_prewarm_service.py`）は、いずれも`effective_max_zoom()`でこの1箇所から導く。
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, NamedTuple, assert_never

#: 配信元がタイルを生成するズームの偶奇。`"all"`は偶奇の制約が無いことを表す。
ZoomUse = Literal["even", "odd", "all"]

#: 配信元のパスの系統（`.../jmatile/data/<系統>/...`）。系統ごとに時刻一覧と更新間隔が別になる。
PathGroup = Literal["risk", "nowc", "rasrf"]


@dataclass(frozen=True)
class JmaTileSpec:
    """1要素分の配信元仕様。要素id（タイルパス中の
    `.../surf/<element_id>/{z}/{x}/{y}.png`）は`JMA_TILE_SPECS`のキーが唯一の持ち主で、
    ここには持たない——両方に書くと、ずれても探索は成功し、取りに行く先だけが変わる。"""

    path_group: PathGroup
    zoom_use: ZoomUse
    max_native_zoom: int
    min_zoom: int = 4
    #: ベクタタイル（.pbf）の中のレイヤー名。ラスタの要素はNone。
    vector_layer: str | None = None


def effective_max_zoom(spec: JmaTileSpec) -> int:
    """実データが存在する最大ズーム。

    `zoom_use`が偶数/奇数のみの場合、`max_native_zoom`がその偶奇に合わないと、その
    ズームのタイルは存在せず空タイルが返る。合う側へ1段下げた値が実際の上限になる。
    """
    z = spec.max_native_zoom
    if spec.zoom_use == "even":
        return z if z % 2 == 0 else z - 1
    if spec.zoom_use == "odd":
        return z if z % 2 == 1 else z - 1
    return z


# 出典は各要素を表示する公式ページが読み込む設定ファイル:
#   キキクル4種 … `bosai/risk/table/risk.properties__<hash>.xml`
#   降水/雷/竜巻 … `bosai/nowc/table/nowc.properties__<hash>.xml`
#   降水短時間予報・線状降水帯予測マップ … `bosai/kaikotan/table/kaikotan.properties__<hash>.xml`
JMA_TILE_SPECS: dict[str, JmaTileSpec] = {
    # キキクル（危険度分布）。土砂・大雨・浸水はラスタ、洪水はベクタ（.pbf）。
    "land": JmaTileSpec("risk", "even", 11),
    "rain_mesh": JmaTileSpec("risk", "even", 11),
    "inund": JmaTileSpec("risk", "even", 11),
    # floodは`zoomUse="even"`を持つが`maxNativeZoom`の記載が無い。同じrisk系の他要素と
    # 同じ11として扱う——z10に実データがありz11・z12が空という実測とも一致する。
    "flood": JmaTileSpec("risk", "even", 11, vector_layer="flood"),
    # 降水ナウキャスト（60分先まで）と降水短時間予報（その先15時間先まで）。
    "hrpns": JmaTileSpec("nowc", "even", 10),
    "rasrf": JmaTileSpec("rasrf", "even", 10),
    # 雷・竜巻ナウキャストはmaxNativeZoomが9で、他のJMAタイルより1段粗い。
    "thns": JmaTileSpec("nowc", "even", 9),
    "trns": JmaTileSpec("nowc", "even", 9),
    # 線状降水帯予測マップ。
    "sjfcstmap": JmaTileSpec("rasrf", "even", 10),
}

#: タイルでは配らない配信要素の系統。落雷の位置（`liden`）は同じ系統の下にGeoJSONで配られる。
#: 1つの要素idの系統は、ここか`JMA_TILE_SPECS`のどちらか一方だけが持つ。
JMA_NON_TILE_PATH_GROUPS: dict[str, PathGroup] = {
    "liden": "nowc",
}


def jma_path_group(element_id: str) -> PathGroup:
    """配信要素のパスの系統。どちらの表にも無い要素idは`KeyError`。"""
    spec = JMA_TILE_SPECS.get(element_id)
    if spec is not None:
        return spec.path_group
    return JMA_NON_TILE_PATH_GROUPS[element_id]


#: 系統ごとの時刻一覧のファイル（公式ページの設定ファイルの`<dataRootUrl>`配下の`<timeFile>`）。
JMA_TARGET_TIME_FILES: dict[PathGroup, tuple[str, ...]] = {
    "risk": ("targetTimes.json",),
    "nowc": ("targetTimes_N1.json", "targetTimes_N2.json", "targetTimes_N3.json"),
    "rasrf": ("targetTimes.json",),
}

#: 時刻一覧が複数のファイルに分かれる系統で、その要素の行が載るファイル。設定ファイルは分け方を
#: 持たず、各ファイルの行の`elements`で決まる（N1・N2は降水の実況・予測、N3は雷・竜巻・落雷）。
#: 系統の全ファイルを読む形にしないのは、要素の行が1件も無いファイルの取得失敗まで、その要素の
#: 失敗に数えることになるため。
JMA_TARGET_TIME_FILES_BY_ELEMENT: dict[str, tuple[str, ...]] = {
    "hrpns": ("targetTimes_N1.json", "targetTimes_N2.json"),
    "thns": ("targetTimes_N3.json",),
    "trns": ("targetTimes_N3.json",),
    "liden": ("targetTimes_N3.json",),
}


#: 系統ごとの時刻一覧の更新間隔（秒）。降水・雷の実況は5分おき、キキクル・降水短時間予報・
#: 線状降水帯予測マップは10分おきに更新される。
JMA_REFRESH_INTERVAL_SECONDS: dict[PathGroup, int] = {
    "nowc": 5 * 60,
    "rasrf": 10 * 60,
    "risk": 10 * 60,
}

#: 時刻一覧の行の並び方。要素ごとに違い、同じ系統・同じファイルでも一致しない。
#: - `nowcast`: その要素の行が時刻順に並ぶ実況＋予測。実況（validtime==basetime）は過去へ長く続く。
#: - `latestFullRun`: 数値予報のラン。系列（`member`）ごとに、有効時刻を複数持つ最新のラン
#:   （単発の中間ランではないもの）だけが完全な予報になる。
#: - `latest`: 実況と予測を配信元が統合済みの「現在」の単一値。最新の行だけが意味を持つ。
TargetTimesReader = Literal["nowcast", "latestFullRun", "latest"]

JMA_TARGET_TIMES_READERS: dict[str, TargetTimesReader] = {
    "hrpns": "nowcast",
    "thns": "nowcast",
    "trns": "nowcast",
    "liden": "nowcast",
    "rasrf": "latestFullRun",
    "land": "latest",
    "rain_mesh": "latest",
    "inund": "latest",
    "flood": "latest",
    "sjfcstmap": "latest",
}


class JmaFrame(NamedTuple):
    """時刻一覧から読み出したコマ1つ。タイルのURLを決める時刻と系列。"""

    basetime: str
    #: 数値予報の系列。系列を持たない行（nowc）は"none"。
    member: str
    validtime: str


def read_target_times(
    reader: TargetTimesReader, rows: Sequence[Mapping[str, Any]], element_id: str
) -> list[JmaFrame]:
    """時刻一覧の行を、その要素のコマ（`validtime`の順）にする。

    画面（frontend `jmaDelivery.ts`の`READERS`）と同じ読み方をする——温めるフレームと在否インデックスの
    フレームは、画面が描くフレームと一致しないと役に立たない（インデックスは一致したフレームにしか使われない）。
    1つの時刻一覧には別の要素の行も載るため、先にその要素の行へ絞る。"""
    frames = [
        JmaFrame(row["basetime"], row.get("member", "none"), row["validtime"])
        for row in rows
        if element_id in row.get("elements", [])
    ]
    match reader:
        case "nowcast":
            return _read_nowcast(frames)
        case "latestFullRun":
            return _read_latest_full_run(frames)
        case "latest":
            return [max(frames, key=lambda frame: frame.basetime)] if frames else []
        case _:
            assert_never(reader)


def _read_nowcast(frames: list[JmaFrame]) -> list[JmaFrame]:
    """最新の実況（`validtime`==`basetime`）より前を捨てる。実況が1つも無ければ何も捨てない。"""
    ordered = sorted(frames, key=lambda frame: frame.validtime)
    observed = [index for index, frame in enumerate(ordered) if frame.validtime == frame.basetime]
    return ordered[observed[-1] :] if observed else ordered


def _read_latest_full_run(frames: list[JmaFrame]) -> list[JmaFrame]:
    """系列ごとに、有効時刻を複数持つ最新のランだけを使う。系列どうしで有効時刻が重なれば新しいランを採る。"""
    by_validtime: dict[str, JmaFrame] = {}
    for member in dict.fromkeys(frame.member for frame in frames):
        of_member = [frame for frame in frames if frame.member == member]
        validtimes_by_run: dict[str, set[str]] = {}
        for frame in of_member:
            validtimes_by_run.setdefault(frame.basetime, set()).add(frame.validtime)
        full_runs = [basetime for basetime, validtimes in validtimes_by_run.items() if len(validtimes) > 1]
        if not full_runs:
            continue
        latest = max(full_runs)
        for frame in of_member:
            taken = by_validtime.get(frame.validtime)
            if frame.basetime == latest and (taken is None or taken.basetime < frame.basetime):
                by_validtime[frame.validtime] = frame
    return sorted(by_validtime.values(), key=lambda frame: frame.validtime)


def jma_target_time_files(element_id: str) -> tuple[str, ...]:
    """その要素の行が載る時刻一覧のファイル名（系統の`.../data/<系統>/`の直下）。

    複数のファイルに分かれる系統で分け方が宣言されていない要素は`KeyError`。"""
    files = JMA_TARGET_TIME_FILES[jma_path_group(element_id)]
    if len(files) == 1:
        return files
    return JMA_TARGET_TIME_FILES_BY_ELEMENT[element_id]


def jma_target_times_paths(element_id: str) -> tuple[str, ...]:
    """その要素の時刻一覧の、配信元のパス（`bosai/jmatile/data/<系統>/<ファイル>`）。"""
    group = jma_path_group(element_id)
    return tuple(f"bosai/jmatile/data/{group}/{name}" for name in jma_target_time_files(element_id))


def has_native_tile(spec: JmaTileSpec, zoom: int) -> bool:
    """そのズームに配信元の実データが存在するか。

    `zoom_use`の偶奇に合わないズームは、配信元が200を返しても中身は空タイルになる。
    """
    if zoom < spec.min_zoom or zoom > effective_max_zoom(spec):
        return False
    if spec.zoom_use == "even":
        return zoom % 2 == 0
    if spec.zoom_use == "odd":
        return zoom % 2 == 1
    return True


def source_zoom_for_interpolation(element_id: str, zoom: int) -> int | None:
    """`zoom`のタイルを補間するために取得すべき親ズーム。補間が不要／不可能ならNone。

    `zoom_use`が偶奇を限る要素では、実データを持つズームが1つおきに並ぶため、親は常に
    `zoom - 1`（そこは必ず反対の偶奇になる）。親が`min_zoom`を下回る場合は補間できない
    （拡大の元が無い）。上限を超えるズームはMapLibre側のoverzoomが担うため対象外。
    """
    spec = JMA_TILE_SPECS.get(element_id)
    if spec is None or spec.zoom_use == "all":
        return None
    if zoom > effective_max_zoom(spec) or zoom < spec.min_zoom:
        return None
    if has_native_tile(spec, zoom):
        return None
    parent = zoom - 1
    return parent if parent >= spec.min_zoom else None
