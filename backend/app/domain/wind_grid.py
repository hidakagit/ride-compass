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

from pydantic import BaseModel

from app.domain.route import Coordinates

# 関東本土7都県（離島除く）のbbox。scripts/collect_jartic.pyのDEFAULT_BBOXと同じ範囲値だが、
# あちらはバッチスクリプト専用の定数でapp本体からは独立しているため、誤って結合させないよう
# 本機能専用の定数として持つ。
WIND_GRID_BBOX: tuple[float, float, float, float] = (138.35, 34.85, 140.95, 37.20)  # (min_lon, min_lat, max_lon, max_lat)
# 格子間隔（度）。関東本土bbox（経度2.6°×緯度2.35°）に対しこの間隔で約26×24=624点になる。
# 格子間隔0.1°（緯度約11km・経度約9km）は、正方格子の最悪ケース（どの地点でも最寄り
# 格子点までの距離が対角線の半分＝約7km以内）がズーム13の表示半径にほぼ収まる値として選んだ。
WIND_GRID_SPACING_DEG = 0.1


def generate_wind_grid_points(
    bbox: tuple[float, float, float, float] = WIND_GRID_BBOX,
    spacing_deg: float = WIND_GRID_SPACING_DEG,
) -> list[Coordinates]:
    """bbox内を格子状に走査した座標列を返す。浮動小数の`+=`による誤差累積を避けるため、
    整数のステップ数から都度座標を計算する（端点が必ず入る保証はしない、密なメッシュを
    要求する用途ではないため許容）。"""
    min_lon, min_lat, max_lon, max_lat = bbox
    lat_steps = int((max_lat - min_lat) / spacing_deg) + 1
    lon_steps = int((max_lon - min_lon) / spacing_deg) + 1
    points = []
    for i in range(lat_steps):
        lat = round(min_lat + i * spacing_deg, 4)
        for j in range(lon_steps):
            lon = round(min_lon + j * spacing_deg, 4)
            points.append(Coordinates(latitude=lat, longitude=lon))
    return points


def nearest_grid_point(
    point: Coordinates,
    bbox: tuple[float, float, float, float] = WIND_GRID_BBOX,
    spacing_deg: float = WIND_GRID_SPACING_DEG,
) -> Coordinates:
    """任意の地点から、generate_wind_grid_pointsと同じ固定ラティス（bboxの原点基準、
    spacing_deg間隔）上の最寄り格子点を返す。way_id→動的値配信層（WindWayService）が、
    タイル中心のような任意座標に対する風を求める際に使う。タイルごとに異なる座標で
    問い合わせると、派生値キャッシュ（dynamic_way_value_cache.py）のキーが隣接タイル間で
    ばらつき共有できなくなるため、常に同じ絶対座標の格子点へ丸める
    （generate_wind_grid_detail_pointsのdocstringにある原点固定の理由と同じ）。

    範囲外の地点はbboxの端へクランプしてから最寄りを求める（呼び出し元がWIND_GRID_BBOX外の
    タイルを渡すことは想定していないが、境界付近での取りこぼしを避ける安全側の処理）。
    """
    min_lon, min_lat, max_lon, max_lat = bbox
    clamped_lat = min(max(point.latitude, min_lat), max_lat)
    clamped_lon = min(max(point.longitude, min_lon), max_lon)
    i = round((clamped_lat - min_lat) / spacing_deg)
    j = round((clamped_lon - min_lon) / spacing_deg)
    return Coordinates(
        latitude=round(min_lat + i * spacing_deg, 4),
        longitude=round(min_lon + j * spacing_deg, 4),
    )


# 詳細格子は「表示中の範囲だけ」を対象にする（全域を常時この密度[0.1°間隔]で計算すると
# 624点より遥かに多くなり、応答サイズと計算量が増すため）。
#
# ここで最も重要な設計判断は、詳細格子の座標を「問い合わせbboxの角」からではなく
# WIND_GRID_BBOXの原点（固定）からのオフセットで計算すること。閲覧地点をそのまま格子の
# 起点にすると、閲覧位置が1pxずれるだけで格子点の絶対座標も全部ずれてしまい、近い場所を
# 見ている別ユーザーとのキャッシュ共有（緯度経度を丸めた
# 値がキー）が効かなくなる。原点を固定し「常に同じ絶対座標の格子点」を生成することで、
# bboxが多少ずれていても重なる範囲では同じ座標がヒットし、既存のTTLキャッシュが
# ユーザー間で共有される。
WIND_GRID_DETAIL_SPACING_DEG = 0.02
# 1リクエストで許容する最大点数（乱用・広すぎるbboxでの過大な同時フェッチを防ぐ）。
# 0.02°間隔で1辺0.6°四方（約60km四方、ズーム10以下では通常発生しない広さ）を敷き詰めると
# 31×31=961点相当のため、余裕を持たせた上限として900点とする。
WIND_GRID_DETAIL_MAX_POINTS = 900

# ズーム依存の格子間隔。ズームインするほど画面上に対する格子1マスの面積が広がり、
# gridFillの色境界が段差として目立ちやすくなる。風の矢印のようにアイコンの表示サイズを
# 大きくする補正では実面積を表すgridFillには通用しない（隙間・重なりが生まれるだけ）ため、
# 実際の格子間隔自体をズームに応じて細かくする。連続的な間隔にすると閲覧者ごとに絶対座標の
# ラティスが微妙にずれてしまいキャッシュ共有（generate_wind_grid_detail_pointsのdocstring
# 参照）が効かなくなるため、離散的な段階のみを許可する。この定数（および
# WIND_GRID_SPACING_DEG・WIND_GRID_DETAIL_SPACING_DEG・WIND_GRID_DETAIL_MAX_POINTS）は
# scripts/export_openapi.pyがwind-grid-config.jsonへ書き出す唯一の情報源であり、フロント側
# windLayer.tsはこのJSONをimportするだけで値を複製しない。
WIND_GRID_DETAIL_ALLOWED_SPACINGS_DEG: tuple[float, ...] = (0.02, 0.01, 0.005, 0.0025)


def generate_wind_grid_detail_points(
    bbox: tuple[float, float, float, float],
    spacing_deg: float = WIND_GRID_DETAIL_SPACING_DEG,
) -> list[Coordinates]:
    """bboxをWIND_GRID_BBOXへクリップした上で、WIND_GRID_BBOXの原点に固定されたラティス
    （spacing_deg間隔の絶対座標グリッド）からbboxに交差する点だけを返す。原点を固定する
    理由は上のコメント（キャッシュ共有）を参照。呼び出し元（api/routers/weather.py）が
    点数の上限チェック（WIND_GRID_DETAIL_MAX_POINTS）を行う想定で、ここでは行わない
    （この関数自体は「bboxに対応する格子点を求める」ことだけに責務を絞る）。"""
    origin_lon, origin_lat, bbox_max_lon, bbox_max_lat = WIND_GRID_BBOX
    min_lon = max(bbox[0], origin_lon)
    min_lat = max(bbox[1], origin_lat)
    max_lon = min(bbox[2], bbox_max_lon)
    max_lat = min(bbox[3], bbox_max_lat)
    if min_lon >= max_lon or min_lat >= max_lat:
        return []

    i_start = math.floor((min_lat - origin_lat) / spacing_deg)
    i_end = math.floor((max_lat - origin_lat) / spacing_deg)
    j_start = math.floor((min_lon - origin_lon) / spacing_deg)
    j_end = math.floor((max_lon - origin_lon) / spacing_deg)

    points = []
    for i in range(i_start, i_end + 1):
        lat = round(origin_lat + i * spacing_deg, 4)
        if lat < origin_lat or lat > bbox_max_lat:
            continue
        for j in range(j_start, j_end + 1):
            lon = round(origin_lon + j * spacing_deg, 4)
            if lon < origin_lon or lon > bbox_max_lon:
                continue
            points.append(Coordinates(latitude=lat, longitude=lon))
    return points


class WindGridPoint(BaseModel):
    """格子点1つぶんの時間別風向・風速・降水量。各配列は応答トップレベルの時刻列
    （JST・1時間刻み）とインデックスが揃っている。特定時刻1点へ収束させず
    配列のまま返すのは、フロント側の時刻スライダーが追加のAPI呼び出し無しで時刻を
    切り替えられるようにするため。

    `times`自体はここには持たない（`WindGridResponse`参照）。全地点を同じ時刻列で
    まとめて読む（msm_client.read_series）ため時刻は全地点で共通であり、624地点ぶん
    複製すると応答サイズの大半（約9割）を時刻文字列の重複が占める。

    precipitation_mm（降水量、mm/h相当）を持つ。風の矢印と降水ナウキャストの延長予報
    （+60分以降）が同じ格子点マップを共有するため、1つのモデルへ両方を持たせている
    （モジュール冒頭のdocstring参照）。"""

    latitude: float
    longitude: float
    wind_speed_ms: list[float]
    wind_direction_deg: list[float]
    precipitation_mm: list[float]


class WindGridResponse(BaseModel):
    """`/api/weather/wind-grid`・`wind-grid-detail`の応答本体。`times`は全格子点で共通の
    時刻配列を1本だけ持つ（各`WindGridPoint`は自分の値配列のみを持ち、インデックスは
    `times`と揃っている）。`WindGridPoint`ごとに`times`を複製すると、624地点では
    非圧縮応答の約54%（gzip圧縮下でも約9%）を時刻文字列の重複が占める。全地点取得失敗等で
    `points`が空の場合は`times`も空になる。"""

    times: list[str]
    points: list[WindGridPoint]
