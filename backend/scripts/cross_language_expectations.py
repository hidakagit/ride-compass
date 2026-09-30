"""backendと画面が同じ計算を持つところの「入力→答え」の表。

入力はここに並べ、答えはbackendの関数が出す（手で書かない）。`export_openapi.py`が
`EXPECTATIONS`の組ごとに`frontend/src/types/generated/<組>-expectations.json`へ書き出し、画面の
テストが全行を画面の関数へ当てる。backendの答えが変わると生成物のドリフト検査が落ち、生成し直すと
画面のテストが落ちる。backendの関数そのものの正しさは、手で書いたあるべき値のpytestが見る。
"""

from collections.abc import Callable

from app.domain.geo import COMPASS_LABELS, LatLonPoint, compass_label, haversine_distance_km
from app.domain.jma_tile_specs import (
    JMA_ELEMENTS,
    JmaFrame,
    JmaTile,
    TargetTimesReader,
    jma_tile_path,
    read_target_times,
)
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


#: 組の名前 → 表を作る関数。組を足すときはここに1行足す（書き出しと置き場の名前はこれから決まる）。
EXPECTATIONS: dict[str, Callable[[], dict[str, list[dict]]]] = {
    "geo": geo_expectations,
    "jma": jma_expectations,
}
