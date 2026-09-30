"""backendと画面が同じ計算を持つところの「入力→答え」の表。

入力はここに並べ、答えはbackendの関数が出す（手で書かない）。`export_openapi.py`が
`EXPECTATIONS`の組ごとに`frontend/src/types/generated/<組>-expectations.json`へ書き出し、画面の
テストが全行を画面の関数へ当てる。backendの答えが変わると生成物のドリフト検査が落ち、生成し直すと
画面のテストが落ちる。backendの関数そのものの正しさは、手で書いたあるべき値のpytestが見る。
"""

from collections.abc import Callable

from app.domain.geo import COMPASS_LABELS, LatLonPoint, compass_label, haversine_distance_km

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


#: 組の名前 → 表を作る関数。組を足すときはここに1行足す（書き出しと置き場の名前はこれから決まる）。
EXPECTATIONS: dict[str, Callable[[], dict[str, list[dict]]]] = {
    "geo": geo_expectations,
}
