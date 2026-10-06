"""backendと画面が同じ計算を持つところの「入力→答え」の表。

入力はここに並べ、答えはbackendの関数が出す（手で書かない）。`export_openapi.py`が
`EXPECTATIONS`の組ごとに`frontend/src/types/generated/<組>-expectations.json`へ書き出し、画面の
テストが全行を画面の関数へ当てる。backendの答えが変わると生成物のドリフト検査が落ち、生成し直すと
画面のテストが落ちる。backendの関数そのものの正しさは、手で書いたあるべき値のpytestが見る。
"""

from collections.abc import Callable, Mapping

from app.domain.axis_definitions import (
    AxisDefinition,
    AxisShape,
    BreakpointLinearShape,
    CategoricalShape,
    MaterialTerm,
    evaluate_axis_values,
    raw_values,
)
from app.domain.axis_display import axis_display_for
from app.domain.geo import COMPASS_LABELS, LatLonPoint, compass_label, haversine_distance_km
from app.domain.jma_tile_specs import (
    JMA_ELEMENTS,
    JmaFrame,
    JmaTile,
    TargetTimesReader,
    jma_tile_path,
    read_target_times,
)
from app.domain.material_catalog import MATERIAL_CATALOG, tile_runtime_scales
from app.domain.registry import AxisDisplaySpec, TileInputSpec
from app.domain.weather_elements import stage_first_frames
from app.infrastructure.jma_tile_client import parse_target_times

# 距離は生成物がどの機械で書いてもバイト単位で同じになる桁へ丸める（numpyの三角関数は
# CPUの命令セットで最下位の桁が変わりうる）。1mmの桁で、式の違いは十分に見分けられる。
_DISTANCE_DECIMALS = 6

# 区分の境界のすぐ手前。境界ちょうどとの違いで丸めの向きが分かれる。
_JUST_BEFORE_DEG = 1e-6

_DISTANCE_PAIRS: list[tuple[LatLonPoint, LatLonPoint]] = [
    (LatLonPoint(35.68, 139.77), LatLonPoint(35.68, 139.77)),  # 同じ地点
    (LatLonPoint(0.0, 139.0), LatLonPoint(0.0, 140.0)),  # 赤道を東西に
    (LatLonPoint(35.0, 139.0), LatLonPoint(35.0, 139.1)),  # 中緯度を東西に
    (LatLonPoint(35.0, 139.0), LatLonPoint(35.1, 139.0)),  # 南北に
    (LatLonPoint(35.68, 139.77), LatLonPoint(34.69, 135.50)),  # 日本の範囲の斜め（東京→大阪）
    (LatLonPoint(43.06, 141.35), LatLonPoint(26.21, 127.68)),  # 日本の範囲の斜め（札幌→那覇）
    (LatLonPoint(10.0, 179.5), LatLonPoint(10.5, -179.5)),  # 経度180度をまたぐ
]


def _bearings() -> list[float]:
    width = 360 / len(COMPASS_LABELS)
    boundaries = [i * width + width / 2 for i in range(len(COMPASS_LABELS))]
    edges = [angle for boundary in boundaries for angle in (boundary, boundary - _JUST_BEFORE_DEG)]
    return [0.0, *edges, -width, -width / 2, 360.0, 360.0 + width / 2, 720.0 + width]


def geo_expectations() -> dict[str, list[dict]]:
    return {
        "compass_label": [
            {"bearing_deg": bearing, "label": compass_label(bearing)} for bearing in _bearings()
        ],
        "distance_km": [
            {
                "from": a._asdict(),
                "to": b._asdict(),
                "km": round(haversine_distance_km(a, b), _DISTANCE_DECIMALS),
            }
            for a, b in _DISTANCE_PAIRS
        ],
    }


def _row(basetime: str, validtime: str, elements: list[str], member: str | None = None) -> dict:
    """時刻一覧の1行（配信元のJSONの形。系列を持たない系統の行には`member`が無い）。"""
    row: dict = {"basetime": basetime, "validtime": validtime, "elements": elements}
    if member is not None:
        row["member"] = member
    return row


def _t(hhmm: str) -> str:
    return f"20260924{hhmm}00"


# 読み方ごとの場面: （場面, 読み方, 要素id, 時刻一覧の行）。行は並べ替えずに渡る順のまま。
_READER_SCENES: list[tuple[str, TargetTimesReader, str, list[dict]]] = [
    (
        "別の要素の行が混ざる",
        "nowcast",
        "thns",
        [
            _row(_t("0010"), _t("0020"), ["thns", "liden"]),
            _row(_t("0010"), _t("0010"), ["thns", "liden"]),
            _row(_t("0015"), _t("0015"), ["liden"]),
            _row(_t("0010"), _t("0030"), ["thns"]),
        ],
    ),
    (
        "実況が無い",
        "nowcast",
        "hrpns",
        [
            _row(_t("0010"), _t("0030"), ["hrpns"]),
            _row(_t("0010"), _t("0020"), ["hrpns"]),
        ],
    ),
    (
        "実況が複数",
        "nowcast",
        "hrpns",
        [
            _row(_t("0000"), _t("0000"), ["hrpns"]),
            _row(_t("0010"), _t("0020"), ["hrpns"]),
            _row(_t("0010"), _t("0010"), ["hrpns"]),
            _row(_t("0005"), _t("0005"), ["hrpns"]),
        ],
    ),
    ("その要素の行が0件", "nowcast", "thns", [_row(_t("0015"), _t("0015"), ["liden"])]),
    (
        "中間ランの単発の行",
        "latestFullRun",
        "rasrf",
        [
            _row(_t("0000"), _t("0100"), ["rasrf"], "immed"),
            _row(_t("0000"), _t("0200"), ["rasrf"], "immed"),
            _row(_t("0010"), _t("0010"), ["rasrf"], "immed"),
            _row("20260923230000", _t("0000"), ["rasrf"], "immed"),
            _row("20260923230000", _t("0100"), ["rasrf"], "immed"),
        ],
    ),
    (
        "系列が2つで有効時刻が重なる",
        "latestFullRun",
        "rasrf",
        [
            _row(_t("0000"), _t("0800"), ["rasrf"], "none"),
            _row(_t("0000"), _t("0600"), ["rasrf"], "none"),
            _row(_t("0010"), _t("0500"), ["rasrf"], "immed"),
            _row(_t("0010"), _t("0600"), ["rasrf"], "immed"),
        ],
    ),
    (
        "別の要素の行が混ざる",
        "latestFullRun",
        "rasrf",
        [
            _row(_t("0000"), _t("0100"), ["rasrf", "sjfcstmap"], "immed"),
            _row(_t("0000"), _t("0200"), ["rasrf"], "immed"),
            _row(_t("0020"), _t("0110"), ["sjfcstmap"], "immed"),
            _row(_t("0020"), _t("0210"), ["sjfcstmap"], "immed"),
        ],
    ),
    ("その要素の行が0件", "latestFullRun", "rasrf", [_row(_t("0020"), _t("0110"), ["sjfcstmap"], "immed")]),
    (
        "別の要素の行が混ざる",
        "latest",
        "land",
        [
            _row(_t("0000"), _t("0000"), ["land", "inund"], "none"),
            _row(_t("0010"), _t("0010"), ["land"], "immed"),
            _row(_t("0020"), _t("0020"), ["inund"], "none"),
        ],
    ),
    ("その要素の行が0件", "latest", "land", [_row(_t("0020"), _t("0020"), ["inund"], "none")]),
]


def _frame(hhmm: str) -> JmaFrame:
    return JmaFrame(_t(hhmm), "none", _t(hhmm))


# 段をつなぐ場面: （場面, 段ごとのコマ（近い時刻の段から、段の中は`validtime`の順））。
_STAGE_SCENES: list[tuple[str, list[list[JmaFrame]]]] = [
    (
        "段が重なる",
        [
            [_frame("0000"), _frame("0100")],
            [_frame("0100"), _frame("0200"), _frame("0300")],
            [_frame("0200"), _frame("0400")],
        ],
    ),
    ("後の段が前の段にすべて含まれる", [[_frame("0000"), _frame("0100"), _frame("0200")], [_frame("0100"), _frame("0200")]]),
    ("途中の段が空", [[_frame("0000")], [], [_frame("0000"), _frame("0100")]]),
    ("先頭の段が空", [[], [_frame("0100"), _frame("0200")]]),
    ("全段が空", [[], []]),
]

# タイルで配る要素すべての、同じコマ・同じタイル座標のタイル。
_TILES = [
    JmaTile(element_id, JmaFrame(_t("0000"), "immed", _t("0100")), 9, 454, 201)
    for element_id, element in JMA_ELEMENTS.items()
    if element.tile is not None
]


def jma_expectations() -> dict[str, list[dict]]:
    return {
        "read_target_times": [
            {
                "scene": scene,
                "reader": reader,
                "element_id": element_id,
                "rows": rows,
                "frames": [
                    frame._asdict() for frame in read_target_times(reader, parse_target_times(rows) or [], element_id)
                ],
            }
            for scene, reader, element_id, rows in _READER_SCENES
        ],
        "stage_first_frames": [
            {
                "scene": scene,
                "stages": [[frame._asdict() for frame in frames] for frames in stages],
                "first_frames": [None if frame is None else frame._asdict() for frame in stage_first_frames(stages)],
            }
            for scene, stages in _STAGE_SCENES
        ],
        "tile_path": [
            {
                "element_id": tile.element_id,
                "frame": tile.frame._asdict(),
                "z": tile.z,
                "x": tile.x,
                "y": tile.y,
                "path": jma_tile_path(tile),
            }
            for tile in _TILES
        ],
    }


# 係数（収録年数の逆数）で割り戻したタイルの値も2進で割り切れる年数。
_ACCIDENT_YEARS = [2019, 2020, 2021, 2022]

#: 道1本の材料の値（材料id → 値。欠損はNone）。
_Road = Mapping[str, object]


def _tile_property(material_id: str) -> str:
    tile_property = MATERIAL_CATALOG[material_id].tile_property
    assert tile_property is not None  # 表の材料はタイルへ焼くものから選ぶ
    return tile_property


def _tile_properties(road: _Road, scales: Mapping[str, float]) -> dict[str, object]:
    """材料の値を、路面タイルへ焼いたときのプロパティにする（`infrastructure/road_graph_repository.py:
    ROAD_SURFACE_TILE_MVT_SQL`の形）。欠損・偽・数値の0はキーごと載らない（密度の0はNULLIFで省く）。
    実行時の係数が要る材料は、材料の値を係数で割り戻したタイルの生値で載る。"""
    properties: dict[str, object] = {}
    for material_id, value in road.items():
        if value is None or value is False or value == 0:
            continue
        tile_property = _tile_property(material_id)
        if tile_property in scales:
            assert isinstance(value, float)
            value = value / scales[tile_property]
        properties[tile_property] = value
    return properties


def _axis(axis_id: str, shape: AxisShape) -> AxisDefinition:
    return AxisDefinition(axis_id=axis_id, label=axis_id, default_weight=1.0, shape=shape)


def _score(shape: AxisShape, road: _Road) -> float | None:
    """評価がその道に付ける値。折れ点の軸は折れ点を通す前の重み付き和（地図の段はこの目盛りで切る）、
    分類の軸は点数。評価できなければNone。"""
    materials = {material_id: [value] for material_id, value in road.items()}
    if isinstance(shape, BreakpointLinearShape):
        [value] = raw_values(shape, materials, 1)
    else:
        [value] = evaluate_axis_values(_axis("score", shape), materials, 1)
    return value


def _linear(*terms: MaterialTerm, breakpoints: list[tuple[float, float]]) -> BreakpointLinearShape:
    return BreakpointLinearShape(terms=list(terms), breakpoints=breakpoints)


def _axis_rows(
    name: str, display: AxisDisplaySpec, roads: dict[str, _Road], answer: Callable[[_Road], float | None]
) -> dict:
    assert display.kind == "ramp", name  # 表の軸は地図に出る形だけ
    scales = tile_runtime_scales(_ACCIDENT_YEARS)
    rows = []
    for road_name, road in roads.items():
        value = answer(road)
        rows.append(
            {"road": road_name, "properties": _tile_properties(road, scales), "value": value, "unknown": value is None}
        )
    return {"axis": name, "display": display.model_dump(mode="json"), "runtime_scales": scales, "roads": rows}


def _derived_axis_rows(name: str, shape: AxisShape, roads: dict[str, _Road]) -> dict:
    """軸の定義から地図の表示を導き、評価の答えと並べる。"""
    return _axis_rows(name, axis_display_for(_axis(name, shape)), roads, lambda road: _score(shape, road))


def _referenced_axis_rows() -> dict:
    """他の軸を参照する項（地図では`TileInputSpec.breakpoints`）。参照先は`AXIS_DEFINITIONS`（DBから読む）に
    無いと導出できないため、表示は導出が作るのと同じ形で組む。答えは参照先の点数を材料にした外側の和。"""
    inner = _linear(MaterialTerm(material="maxspeed_kmh"), breakpoints=[(30.0, 0.0), (60.0, 50.0), (90.0, 100.0)])
    outer_weight = 0.5
    outer = _linear(
        MaterialTerm(material="inner", weight=outer_weight, required=False),
        MaterialTerm(material="intersection_count_per_km"),
        breakpoints=[(0.0, 0.0), (60.0, 100.0)],
    )
    display = AxisDisplaySpec(
        kind="ramp",
        tile_inputs=[
            TileInputSpec(property=_tile_property("maxspeed_kmh"), breakpoints=inner.breakpoints, weight=outer_weight),
            TileInputSpec(property=_tile_property("intersection_count_per_km")),
        ],
        thresholds=[x for x, _ in outer.breakpoints[1:]],
    )

    def answer(road: _Road) -> float | None:
        materials = {material_id: [value] for material_id, value in road.items()}
        [inner_score] = evaluate_axis_values(_axis("inner", inner), materials, 1)
        return _score(outer, {**road, "inner": inner_score})

    roads: dict[str, _Road] = {
        "折れ点の間（点数を小数1桁へ丸める）": {"maxspeed_kmh": 40.0, "intersection_count_per_km": 2.0},
        "折れ点より下（端の点数）": {"maxspeed_kmh": 20.0, "intersection_count_per_km": 2.0},
        "折れ点より上（端の点数）": {"maxspeed_kmh": 100.0, "intersection_count_per_km": 2.0},
        "参照先の材料が欠けた（任意の項は寄与0）": {"maxspeed_kmh": None, "intersection_count_per_km": 2.0},
    }
    return _axis_rows("他の軸を参照する項", display, roads, answer)


def axis_ramp_expectations() -> dict[str, list[dict]]:
    """地図のramp軸（タイルの材料で道を塗る軸）が道1本に付ける値と「不明」を、形ごとに評価の答えと並べる。

    必須の材料が欠けた道・全項の材料が欠けた道は入れない——評価は不能、地図は寄与0で、タイルの形では
    欠損と0を見分けられない（`docs/modules/backend/axis-studio.md`「暗黙の前提」）。"""
    return {
        "axes": [
            _derived_axis_rows(
                "数値の材料（重み違いの複数項）",
                _linear(
                    MaterialTerm(material="built_percent", weight=1.5),
                    MaterialTerm(material="trees_percent", weight=-0.5),
                    breakpoints=[(0.0, 0.0), (50.0, 50.0), (100.0, 100.0)],
                ),
                {
                    "両方ある": {"built_percent": 40.0, "trees_percent": 10.0},
                    "片方が0（タイルに載らない）": {"built_percent": 0.0, "trees_percent": 20.0},
                },
            ),
            _derived_axis_rows(
                "任意の材料",
                _linear(
                    MaterialTerm(material="intersection_count_per_km"),
                    MaterialTerm(material="poi_signal_per_km", weight=2.0, required=False),
                    breakpoints=[(0.0, 0.0), (5.0, 50.0), (10.0, 100.0)],
                ),
                {
                    "両方ある": {"intersection_count_per_km": 3.0, "poi_signal_per_km": 1.5},
                    "任意の材料が欠けた": {"intersection_count_per_km": 3.0, "poi_signal_per_km": None},
                },
            ),
            _derived_axis_rows(
                "真偽の材料の重み付き和",
                _linear(
                    MaterialTerm(material="lit", weight=10.0),
                    MaterialTerm(material="has_tunnel", weight=5.0),
                    breakpoints=[(0.0, 0.0), (15.0, 100.0)],
                ),
                {
                    "片方が真": {"lit": True, "has_tunnel": False},
                    "両方が偽（タイルに載らない）": {"lit": False, "has_tunnel": False},
                    "両方が真": {"lit": True, "has_tunnel": True},
                },
            ),
            _derived_axis_rows(
                "真偽の分類",
                CategoricalShape(material="bridge", mapping={True: 80.0, False: 10.0}),
                {"真": {"bridge": True}, "偽（タイルに載らない）": {"bridge": False}},
            ),
            _derived_axis_rows(
                "3値以上の分類",
                CategoricalShape(material="highway", mapping={"primary": 60.0, "residential": 20.0, "cycleway": 0.0}),
                {
                    "登録した値": {"highway": "primary"},
                    "点数0の登録した値": {"highway": "cycleway"},
                    "未登録の値": {"highway": "service"},
                    "欠けた": {"highway": None},
                },
            ),
            _derived_axis_rows(
                "実行時の係数が要る材料",
                _linear(
                    MaterialTerm(material="accident_count_per_km_year", weight=2.0),
                    MaterialTerm(material="built_percent", weight=0.5),
                    breakpoints=[(0.0, 0.0), (20.0, 100.0)],
                ),
                {
                    "両方ある": {"accident_count_per_km_year": 0.5, "built_percent": 30.0},
                    "係数の要る材料が0": {"accident_count_per_km_year": 0.0, "built_percent": 30.0},
                },
            ),
            _referenced_axis_rows(),
        ],
    }


#: 組の名前 → 表を作る関数。組を足すときはここに1行足す（書き出しと置き場の名前はこれから決まる）。
EXPECTATIONS: dict[str, Callable[[], dict[str, list[dict]]]] = {
    "geo": geo_expectations,
    "jma": jma_expectations,
    "axis-ramp": axis_ramp_expectations,
}
