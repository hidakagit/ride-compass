"""風・降水（延長予報）の格子点マップ。

気象庁MSM（`infrastructure/msm_client.py`、CC-BY-4.0）の格子を自前の格子点へ双一次補間で
サンプリングし、フロント側でMapLibre標準のsymbolレイヤー（アイコンを独自定義、向き・
長さ・色すべて自由に設定可能）として描画する。

この格子点マップは風に加えて`precipitation`（降水量mm/h）も配信する。気象庁の降水
ナウキャスト自体は+60分が上限（JMA提供APIの仕様上の制約であり回避不可）のため、
+60分より先はこの格子（MSM・1時間刻み。長さはrunごとの予報時間に従う）が担う。
風・降水はMSMの同じ読み出しでまとめて得られる。

このモジュール自体はexternal APIを叩かない純粋な座標生成のみを持つ（フェッチは
services/weather_service.pyのget_wind_grid、APIエンドポイントはapi/routers/weather.py）。
"""

import math


from app.domain.route import Coordinates
from app.domain.strict_model import StrictModel

# 関東本土7都県（離島除く）のbbox。
WIND_GRID_BBOX: tuple[float, float, float, float] = (138.35, 34.85, 140.95, 37.20)  # (min_lon, min_lat, max_lon, max_lat)
# 格子間隔（度）。0.1°（緯度約11km・経度約9km）は、正方格子の最悪ケース（どの地点でも
# 最寄り格子点まで対角線の半分＝約7km以内）がズーム13の表示半径にほぼ収まる値。
WIND_GRID_SPACING_DEG = 0.1


def _lattice_coordinate(origin_deg: float, index: int, spacing_deg: float) -> float:
    """ラティス上の1点の絶対座標。浮動小数の`+=`による誤差累積を避けるため整数の索引から
    都度計算する。格子を生成する側と最寄りを求める側はどちらもこの関数で座標を決め、同じ
    格子点は呼び出しをまたいで同じ値になる。"""
    return round(origin_deg + index * spacing_deg, 4)


def _last_index(span_deg: float, spacing_deg: float) -> int:
    """原点からspan_deg以内に収まる最後の索引（端点が必ず格子点になる保証はしない、
    密なメッシュを要求する用途ではないため許容）。"""
    return int(span_deg / spacing_deg)


def generate_wind_grid_points(
    bbox: tuple[float, float, float, float] = WIND_GRID_BBOX,
    spacing_deg: float = WIND_GRID_SPACING_DEG,
) -> list[Coordinates]:
    """bbox内を格子状に走査した座標列を返す。"""
    min_lon, min_lat, max_lon, max_lat = bbox
    return [
        Coordinates(
            latitude=_lattice_coordinate(min_lat, i, spacing_deg),
            longitude=_lattice_coordinate(min_lon, j, spacing_deg),
        )
        for i in range(_last_index(max_lat - min_lat, spacing_deg) + 1)
        for j in range(_last_index(max_lon - min_lon, spacing_deg) + 1)
    ]


def nearest_grid_point(
    point: Coordinates,
    bbox: tuple[float, float, float, float] = WIND_GRID_BBOX,
    spacing_deg: float = WIND_GRID_SPACING_DEG,
) -> Coordinates:
    """任意の地点から、generate_wind_grid_pointsと同じ固定ラティス（bboxの原点基準、
    spacing_deg間隔）上の最寄り格子点を返す。

    範囲外の地点はbboxの端へクランプしてから最寄りを求める（境界付近での取りこぼしを
    避ける安全側の処理）。
    """
    min_lon, min_lat, max_lon, max_lat = bbox
    clamped_lat = min(max(point.latitude, min_lat), max_lat)
    clamped_lon = min(max(point.longitude, min_lon), max_lon)
    # 最寄りが最後の格子点より先になることがある（bboxの幅が間隔の整数倍とは限らない）。
    i = min(round((clamped_lat - min_lat) / spacing_deg), _last_index(max_lat - min_lat, spacing_deg))
    j = min(round((clamped_lon - min_lon) / spacing_deg), _last_index(max_lon - min_lon, spacing_deg))
    return Coordinates(
        latitude=_lattice_coordinate(min_lat, i, spacing_deg),
        longitude=_lattice_coordinate(min_lon, j, spacing_deg),
    )


# 詳細格子は「表示中の範囲だけ」を対象にする（全域をこの密度で計算すると応答サイズと
# 計算量が増すため）。座標は問い合わせ範囲の角ではなくWIND_GRID_BBOXの原点から数える
# （理由はdocs/modules/backend/weather-dynamic-layers.md「詳細格子の座標と間隔」節）。
WIND_GRID_DETAIL_SPACING_DEG = 0.02
# 1リクエストで許容する最大点数（乱用・広すぎるbboxでの過大な同時フェッチを防ぐ）。
# ズーム10以下では通常発生しない広さ（約60km四方）を詳細間隔で敷き詰めた点数に、
# 少し余裕を持たせた値。
WIND_GRID_DETAIL_MAX_POINTS = 900

# 詳細格子の問い合わせが受け付ける間隔の下限（度）。これ以上なら任意の間隔を受け付ける
# （根拠と下げられる限界はdocs/modules/backend/weather-dynamic-layers.md「詳細格子の座標と間隔」）。
WIND_GRID_DETAIL_MIN_SPACING_DEG = 0.0025


def _detail_index_ranges(bbox: tuple[float, float, float, float], spacing_deg: float) -> tuple[range, range]:
    """bboxをWIND_GRID_BBOXへクリップした上で、WIND_GRID_BBOXの原点に固定されたラティス
    （spacing_deg間隔の絶対座標グリッド）のうちbboxに交差する点の緯度方向・経度方向の索引の範囲。
    点数を数える側と点を作る側はどちらもこの範囲に従う。"""
    origin_lon, origin_lat, bbox_max_lon, bbox_max_lat = WIND_GRID_BBOX
    min_lon = max(bbox[0], origin_lon)
    min_lat = max(bbox[1], origin_lat)
    max_lon = min(bbox[2], bbox_max_lon)
    max_lat = min(bbox[3], bbox_max_lat)
    if min_lon >= max_lon or min_lat >= max_lat:
        return range(0), range(0)

    # 索引の範囲がクリップ後のbboxから決まるため、ここで改めて範囲を確かめる必要はない
    # （開始は0以上、終わりはクリップ後の端を超えない）。
    return (
        range(math.floor((min_lat - origin_lat) / spacing_deg), math.floor((max_lat - origin_lat) / spacing_deg) + 1),
        range(math.floor((min_lon - origin_lon) / spacing_deg), math.floor((max_lon - origin_lon) / spacing_deg) + 1),
    )


def count_wind_grid_detail_points(
    bbox: tuple[float, float, float, float],
    spacing_deg: float = WIND_GRID_DETAIL_SPACING_DEG,
) -> int:
    """generate_wind_grid_detail_pointsが返す点の数を、点を作らずに求める。"""
    rows, columns = _detail_index_ranges(bbox, spacing_deg)
    return len(rows) * len(columns)


def generate_wind_grid_detail_points(
    bbox: tuple[float, float, float, float],
    spacing_deg: float = WIND_GRID_DETAIL_SPACING_DEG,
) -> list[Coordinates]:
    """bboxに交差する詳細格子の点（範囲は_detail_index_ranges）を返す。点数の上限
    （WIND_GRID_DETAIL_MAX_POINTS）はここでは確かめない——呼び出し元が点を作る前に
    count_wind_grid_detail_pointsで確かめる。"""
    rows, columns = _detail_index_ranges(bbox, spacing_deg)
    origin_lon, origin_lat, _, _ = WIND_GRID_BBOX
    return [
        Coordinates(
            latitude=_lattice_coordinate(origin_lat, i, spacing_deg),
            longitude=_lattice_coordinate(origin_lon, j, spacing_deg),
        )
        for i in rows
        for j in columns
    ]


class WindGridPoint(StrictModel):
    """格子点1つぶんの時間別風向・風速・降水量。各配列は応答トップレベルの時刻列
    （JST・1時間刻み）とインデックスが揃っている。特定時刻1点へ収束させず
    配列のまま返すのは、フロント側の時刻スライダーが追加のAPI呼び出し無しで時刻を
    切り替えられるようにするため。

    `times`自体はここには持たない（`WindGridResponse`参照）——時刻は全地点で共通で、
    地点ごとに複製すると応答サイズの大半を時刻文字列の重複が占める。"""

    latitude: float
    longitude: float
    wind_speed_ms: list[float]
    wind_direction_deg: list[float]
    precipitation_mm: list[float]


class WindGridResponse(StrictModel):
    """`/api/weather/wind-grid`・`wind-grid-detail`の応答本体。`times`は全格子点で共通の
    時刻配列を1本だけ持つ（各`WindGridPoint`は自分の値配列のみを持ち、インデックスは
    `times`と揃っている）。全地点取得失敗等で`points`が空の場合は`times`も空になる。"""

    times: list[str]
    points: list[WindGridPoint]
