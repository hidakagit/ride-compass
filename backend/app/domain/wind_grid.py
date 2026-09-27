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

from app.domain.region import BoundingBox
from app.domain.route import Coordinates
from app.domain.strict_model import StrictModel
from app.domain.wind import grid_index_at_or_below

# 格子間隔（度）。0.1°（緯度約11km・経度約9km）は、正方格子の最悪ケース（どの地点でも
# 最寄り格子点まで対角線の半分＝約7km以内）がズーム13の表示半径にほぼ収まる値。
WIND_GRID_SPACING_DEG = 0.1


def _lattice_coordinate(index: int, spacing_deg: float) -> float:
    """ラティス上の1点の絶対座標。浮動小数の`+=`による誤差累積を避けるため整数の索引から
    都度計算する。格子を生成する側はどれもこの関数で座標を決め、同じ格子点は呼び出しを
    またいで同じ値になる。"""
    return round(index * spacing_deg, 4)


def generate_wind_grid_points(area: BoundingBox) -> list[Coordinates]:
    """対象範囲`area`全体の、`WIND_GRID_SPACING_DEG`間隔の格子点。"""
    return generate_wind_grid_detail_points(area, area, WIND_GRID_SPACING_DEG)


# 詳細格子は「表示中の範囲だけ」を対象にする（全域をこの密度で計算すると応答サイズと
# 計算量が増すため）。座標は問い合わせ範囲の角からも対象範囲の角からも数えず、緯度・経度0度から数える
# （理由はdocs/modules/backend/weather-dynamic-layers.md「詳細格子の座標と間隔」節）。
WIND_GRID_DETAIL_SPACING_DEG = 0.02
# 1リクエストで許容する最大点数（乱用・広すぎるbboxでの過大な同時フェッチを防ぐ）。
# ズーム10以下では通常発生しない広さ（約60km四方）を詳細間隔で敷き詰めた点数に、
# 少し余裕を持たせた値。
WIND_GRID_DETAIL_MAX_POINTS = 900

# 詳細格子の問い合わせが受け付ける間隔の下限（度）。これ以上なら任意の間隔を受け付ける
# （根拠と下げられる限界はdocs/modules/backend/weather-dynamic-layers.md「詳細格子の座標と間隔」）。
WIND_GRID_DETAIL_MIN_SPACING_DEG = 0.0025


def _detail_index_ranges(area: BoundingBox, bbox: BoundingBox, spacing_deg: float) -> tuple[range, range]:
    """bboxを対象範囲`area`へクリップした上で、緯度・経度0度から`spacing_deg`ずつ数えたラティスのうち
    bboxに交差する点の緯度方向・経度方向の索引の範囲。点数を数える側と点を作る側はどちらもこの範囲に従う。"""
    min_lon = max(bbox.min_longitude, area.min_longitude)
    min_lat = max(bbox.min_latitude, area.min_latitude)
    max_lon = min(bbox.max_longitude, area.max_longitude)
    max_lat = min(bbox.max_latitude, area.max_latitude)
    if min_lon >= max_lon or min_lat >= max_lat:
        return range(0), range(0)
    return (
        range(grid_index_at_or_below(min_lat, spacing_deg), grid_index_at_or_below(max_lat, spacing_deg) + 1),
        range(grid_index_at_or_below(min_lon, spacing_deg), grid_index_at_or_below(max_lon, spacing_deg) + 1),
    )


def count_wind_grid_detail_points(
    area: BoundingBox,
    bbox: BoundingBox,
    spacing_deg: float = WIND_GRID_DETAIL_SPACING_DEG,
) -> int:
    """generate_wind_grid_detail_pointsが返す点の数を、点を作らずに求める。"""
    rows, columns = _detail_index_ranges(area, bbox, spacing_deg)
    return len(rows) * len(columns)


def generate_wind_grid_detail_points(
    area: BoundingBox,
    bbox: BoundingBox,
    spacing_deg: float = WIND_GRID_DETAIL_SPACING_DEG,
) -> list[Coordinates]:
    """bboxに交差する詳細格子の点（範囲は_detail_index_ranges）を返す。点数の上限
    （WIND_GRID_DETAIL_MAX_POINTS）はここでは確かめない——呼び出し元が点を作る前に
    count_wind_grid_detail_pointsで確かめる。"""
    rows, columns = _detail_index_ranges(area, bbox, spacing_deg)
    return [
        Coordinates(latitude=_lattice_coordinate(i, spacing_deg), longitude=_lattice_coordinate(j, spacing_deg))
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
