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

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, NamedTuple, assert_never

#: 配信元がタイルを生成するズームの偶奇。`"all"`は偶奇の制約が無いことを表す。
ZoomUse = Literal["even", "odd", "all"]

#: 配信元のパスの系統（`.../jmatile/data/<系統>/...`）。系統ごとに時刻一覧と更新間隔が別になる。
PathGroup = Literal["risk", "nowc", "rasrf"]


#: 時刻一覧の行の並び方。要素ごとに違い、同じ系統・同じファイルでも一致しない。
#: - `nowcast`: その要素の行が時刻順に並ぶ実況＋予測。実況（validtime==basetime）は過去へ長く続く。
#: - `latestFullRun`: 数値予報のラン。系列（`member`）ごとに、有効時刻を複数持つ最新のラン
#:   （単発の中間ランではないもの）だけが完全な予報になる。
#: - `latest`: 実況と予測を配信元が統合済みの「現在」の単一値。最新の行だけが意味を持つ。
TargetTimesReader = Literal["nowcast", "latestFullRun", "latest"]


@dataclass(frozen=True)
class JmaTileSpec:
    """タイルで配る要素の、タイルの仕様。"""

    zoom_use: ZoomUse
    max_native_zoom: int
    #: ベクタタイル（.pbf）の中のレイヤー名。ラスタの要素はNone。
    vector_layer: str | None = None
    #: 降水の段の色（`infrastructure/jma_tile_recolor.py: JMA_PRECIPITATION_TILE_COLORS`）で塗った画像で、中継がアプリの
    #: 降水の段の色へ塗り替えて配る。
    precipitation_colors: bool = False


#: どの要素も配信元に実データがある最小ズーム。
JMA_TILE_MIN_ZOOM = 4


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


@dataclass(frozen=True)
class JmaElement:
    """配信要素1つの宣言。要素id（配信元のパス`.../<系統>/.../surf/<element_id>/`）は`JMA_ELEMENTS`のキーが
    持ち、ここには持たない——両方に書くと、ずれても探索は成功し、取りに行く先だけが変わる。"""

    path_group: PathGroup
    #: その要素の行が載る時刻一覧のファイル（系統の`.../data/<系統>/`の直下）。
    time_files: tuple[str, ...]
    reader: TargetTimesReader
    #: タイルで配る要素の仕様。タイルで配らない要素（コマごとの地物のGeoJSON。例: 落雷の地点）はNone。
    tile: JmaTileSpec | None = None
    #: 配信の遅れ（分。公式の画面の設定の`dataDelay`）。配信元は時刻一覧に載せたコマをこの幅のあいだ配信しておらず、
    #: 画面はその要素の最新の`basetime`から幅に入るコマを、幅の端まで前の`basetime`へずらして読む（公式の画面と同じ）。
    data_delay_minutes: int = 0
    #: 予測が届く先（分。1つの`basetime`の実況から）。地図の説明の文と凡例が引く。予測を持たない要素はNone。
    forecast_minutes: int | None = None

    def __post_init__(self) -> None:
        # ずらし方は画面の読み方だけが持ち、プリウォーム（タイルだけを温める）の読み方`read_target_times`は持たない。
        if self.tile is not None and self.data_delay_minutes:
            raise ValueError("タイルで配る要素に配信の遅れを宣言するなら、プリウォームの読み方にも同じずらしが要る")


#: 降水ナウキャストと降水短時間予報のタイルの仕様（同じズームで、同じ降水の段の色で塗る）。
_PRECIPITATION_TILE = JmaTileSpec("even", 10, precipitation_colors=True)

# 出典は各要素を表示する公式ページが読み込む設定ファイル（系統・時刻一覧のファイル・ズーム）:
#   キキクル4種 … `bosai/risk/table/risk.properties__<hash>.xml`
#   降水/雷/竜巻/線状降水帯の雨域 … `bosai/nowc/table/nowc.properties__<hash>.xml`
#   降水短時間予報・線状降水帯予測マップ … `bosai/kaikotan/table/kaikotan.properties__<hash>.xml`
# 設定ファイルの名前は配信元の更新ごとに変わるハッシュを含み、決まった所から取れないため、ここへ写して持つ。
# 設定ファイルは時刻一覧の分け方を持たず、分かれている系統では各ファイルの行の`elements`で決まる
# （nowcのN1・N2は降水の実況・予測、N3は雷・竜巻・落雷・線状降水帯の雨域）。系統の全ファイルを読む形にしないのは、
# 要素の行が1件も無いファイルの取得失敗まで、その要素の失敗に数えることになるため。
JMA_ELEMENTS: dict[str, JmaElement] = {
    # キキクル（危険度分布）。土砂・大雨・浸水はラスタ、洪水はベクタ（.pbf）。
    "land": JmaElement("risk", ("targetTimes.json",), "latest", JmaTileSpec("even", 11)),
    "rain_mesh": JmaElement("risk", ("targetTimes.json",), "latest", JmaTileSpec("even", 11)),
    "inund": JmaElement("risk", ("targetTimes.json",), "latest", JmaTileSpec("even", 11)),
    # floodは`zoomUse="even"`を持つが`maxNativeZoom`の記載が無い。同じrisk系の他要素と
    # 同じ11として扱う——z10に実データがありz11・z12が空という実測とも一致する。
    "flood": JmaElement("risk", ("targetTimes.json",), "latest", JmaTileSpec("even", 11, vector_layer="flood")),
    # 降水ナウキャスト（60分先まで）と降水短時間予報（その先15時間先まで）。
    "hrpns": JmaElement(
        "nowc", ("targetTimes_N1.json", "targetTimes_N2.json"), "nowcast", _PRECIPITATION_TILE, forecast_minutes=60
    ),
    "rasrf": JmaElement("rasrf", ("targetTimes.json",), "latestFullRun", _PRECIPITATION_TILE, forecast_minutes=15 * 60),
    # 雷・竜巻ナウキャストはmaxNativeZoomが9で、他のJMAタイルより1段粗い。
    # どちらも実況と60分先まで。
    "thns": JmaElement("nowc", ("targetTimes_N3.json",), "nowcast", JmaTileSpec("even", 9), forecast_minutes=60),
    "trns": JmaElement("nowc", ("targetTimes_N3.json",), "nowcast", JmaTileSpec("even", 9), forecast_minutes=60),
    # 落雷の位置。タイルではなく、同じ系統の下にGeoJSONで配られる。
    "liden": JmaElement("nowc", ("targetTimes_N3.json",), "nowcast"),
    # 線状降水帯の雨域（公式の既定の表示「代表楕円表示方式」が読む2つ）。落雷と同じくコマごとのGeoJSONで、
    # 1つの`basetime`が実況と30分先までの予測を持つ。時刻一覧は最新の`basetime`の実況と20分先までを載せるが、
    # 配信は遅れるので、公式の画面は1つ前の`basetime`の実況と予測を読む。
    "slmcs_unify": JmaElement("nowc", ("targetTimes_N3.json",), "nowcast", data_delay_minutes=10),
    "slmcs_unifyfcst": JmaElement(
        "nowc", ("targetTimes_N3.json",), "nowcast", data_delay_minutes=10, forecast_minutes=30
    ),
    # 線状降水帯予測マップ。
    "sjfcstmap": JmaElement("rasrf", ("targetTimes.json",), "latest", JmaTileSpec("even", 10)),
}


#: 系統ごとの時刻一覧の更新間隔（秒）。系統の中で最も短い要素の更新間隔にする——長い要素を早めに取り直しても
#: 古い表示にはならない。出典（気象庁の公表値）: 高解像度降水ナウキャスト5分・雷ナウキャスト・竜巻発生確度ナウキャスト
#: 10分・速報版降水短時間予報10分（https://www.data.jma.go.jp/developer/weatherdataguide/appendix/2-1-b.html）、
#: 土砂キキクル10分（https://www.jma.go.jp/jma/kishou/know/bosai/doshakeikai.html）、線状降水帯予測マップ10分
#: （配信資料に関する技術情報第666号 https://www.data.jma.go.jp/suishin/jyouhou/pdf/666.pdf の「作成頻度」）。
JMA_REFRESH_INTERVAL_SECONDS: dict[PathGroup, int] = {
    "nowc": 5 * 60,
    "rasrf": 10 * 60,
    "risk": 10 * 60,
}


class JmaFrame(NamedTuple):
    """時刻一覧から読み出したコマ1つ。タイルのURLを決める時刻と系列。"""

    basetime: str
    #: 数値予報の系列。系列を持たない行（nowc）は"none"。
    member: str
    validtime: str


class TargetTimesRow(NamedTuple):
    """時刻一覧の1行（1つのコマと、そのコマのタイルがある配信要素）。"""

    frame: JmaFrame
    elements: tuple[str, ...]


def read_target_times(reader: TargetTimesReader, rows: Sequence[TargetTimesRow], element_id: str) -> list[JmaFrame]:
    """時刻一覧の行を、その要素のコマ（`validtime`の順）にする。

    画面も同じ読み方でコマにする——温めるフレームと在否インデックスのフレームは、画面が描くフレームと一致しないと
    役に立たない（インデックスは一致したフレームにしか使われない）。同じコマになることは、場面ごとの時刻一覧と
    この関数の答えを`scripts/cross_language_expectations.py: jma_expectations`が表にして配り、画面のテストが通す。
    1つの時刻一覧には別の要素の行も載るため、先にその要素の行へ絞る。時刻一覧の形は
    `infrastructure/jma_tile_client.py: parse_target_times`が行へ解く。"""
    frames = [row.frame for row in rows if element_id in row.elements]
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


_DATA_ROOT = "bosai/jmatile/data"
#: 時刻一覧の置き場。
_TARGET_TIMES_PATH = _DATA_ROOT + "/{group}/{file}"
#: 配信要素の1コマの置き場。この下にタイル（地図の`{z}/{x}/{y}`）か、タイルで配らない要素の地物（GeoJSON）がある。
_FRAME_PATH = _DATA_ROOT + "/{group}/{basetime}/{member}/{validtime}/surf/{element}"
_TILE_FILE = "{z}/{x}/{y}.{extension}"
_FEATURES_FILE = "data.geojson?id={element}"
#: テンプレートの埋める所（`{名前}`）。画面も同じ書き方で埋める。
TEMPLATE_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _fill(template: str, **values: str) -> str:
    """`{名前}`を値で埋める。渡さなかった名前は`{名前}`のまま残す。"""
    return TEMPLATE_PLACEHOLDER.sub(lambda match: values.get(match.group(1), match.group(0)), template)


def _tile_extension(spec: JmaTileSpec) -> str:
    """配信元はベクタをMapbox Vector Tile（.pbf）、ラスタを画像（.png）で配る。"""
    return "pbf" if spec.vector_layer else "png"


def jma_target_times_paths(element_id: str) -> tuple[str, ...]:
    """その要素の時刻一覧の、配信元のパス。"""
    element = JMA_ELEMENTS[element_id]
    return tuple(_fill(_TARGET_TIMES_PATH, group=element.path_group, file=name) for name in element.time_files)


def jma_url_template(element_id: str) -> str:
    """その要素のコマの、配信元のパスのテンプレート。時刻と系列（`JmaFrame`の項目名の`{basetime}`等）と、
    タイルならタイル座標（`{z}/{x}/{y}`）が埋まらずに残る。画面へは生成物で届き、画面もこれを埋めて取りに行く。"""
    element = JMA_ELEMENTS[element_id]
    if element.tile is None:
        return _fill(f"{_FRAME_PATH}/{_FEATURES_FILE}", group=element.path_group, element=element_id)
    return _fill(
        f"{_FRAME_PATH}/{_TILE_FILE}",
        group=element.path_group,
        element=element_id,
        extension=_tile_extension(element.tile),
    )


class JmaTile(NamedTuple):
    """配信元のタイル1枚。"""

    element_id: str
    frame: JmaFrame
    z: int
    x: int
    y: int


def jma_tile_path(tile: JmaTile) -> str:
    """タイルの、配信元のパス。タイルで配らない要素は`ValueError`。"""
    if JMA_ELEMENTS[tile.element_id].tile is None:
        raise ValueError(f"タイルで配らない配信要素: {tile.element_id}")
    return _fill(
        jma_url_template(tile.element_id),
        **tile.frame._asdict(),
        z=str(tile.z),
        x=str(tile.x),
        y=str(tile.y),
    )


def jma_tile_spec(element_id: str) -> JmaTileSpec:
    """タイルで配る要素のタイルの仕様。宣言の無い要素idは`KeyError`、タイルで配らない要素は`ValueError`。"""
    tile = JMA_ELEMENTS[element_id].tile
    if tile is None:
        raise ValueError(f"タイルで配らない配信要素: {element_id}")
    return tile


def has_native_tile(spec: JmaTileSpec, zoom: int) -> bool:
    """そのズームに配信元の実データが存在するか。

    `zoom_use`の偶奇に合わないズームは、配信元が200を返しても中身は空タイルになる。
    """
    if zoom < JMA_TILE_MIN_ZOOM or zoom > effective_max_zoom(spec):
        return False
    if spec.zoom_use == "even":
        return zoom % 2 == 0
    if spec.zoom_use == "odd":
        return zoom % 2 == 1
    return True


def source_zoom_for_interpolation(element_id: str, zoom: int) -> int | None:
    """`zoom`のタイルを補間するために取得すべき親ズーム。補間が不要／不可能ならNone。

    `zoom_use`が偶奇を限る要素では、実データを持つズームが1つおきに並ぶため、親は常に
    `zoom - 1`（そこは必ず反対の偶奇になる）。親が`JMA_TILE_MIN_ZOOM`を下回る場合は補間できない
    （拡大の元が無い）。上限を超えるズームはMapLibre側のoverzoomが担うため対象外。
    """
    element = JMA_ELEMENTS.get(element_id)
    spec = element.tile if element is not None else None
    if spec is None or spec.zoom_use == "all":
        return None
    if zoom > effective_max_zoom(spec) or zoom < JMA_TILE_MIN_ZOOM:
        return None
    if has_native_tile(spec, zoom):
        return None
    parent = zoom - 1
    return parent if parent >= JMA_TILE_MIN_ZOOM else None


def with_interpolated_zooms(
    element_id: str, zooms: dict[int, list[list[int]]]
) -> dict[int, list[list[int]]]:
    """実データのあるズームの在否（ズーム→中身のあるタイルの`[x, y]`）に、補間で埋めるズームの在否を親から補う。

    補間結果が空になるのは親が空のときだけなので、**親に中身のあるタイルの4象限**を
    そのまま子ズームの中身ありとする（追加の取得は要らない）。
    """
    if not zooms:
        return zooms
    filled = dict(zooms)
    for zoom in range(min(zooms) + 1, effective_max_zoom(jma_tile_spec(element_id)) + 1):
        if source_zoom_for_interpolation(element_id, zoom) is None:
            continue
        parents = filled.get(zoom - 1)
        if not parents:
            continue
        filled[zoom] = [
            [x * 2 + dx, y * 2 + dy] for x, y in parents for dx in (0, 1) for dy in (0, 1)
        ]
    return filled
