"""風・降水（延長予報）の格子点マップ（改善計画T178フォローアップ、T183で降水へ拡張）。

`@openmeteo/weather-map-layer`（GPLv2、内部の.omファイルデコーダ@openmeteo/file-reader等も
同じくGPL-2.0-only）を使った気象庁MSM由来の風矢印描画は、(1) GPLv2依存が避けられない、
(2) 矢印の長さがライブラリ側でズームレベル依存に固定され自由に表現できない、という
2つの制約に実機で行き当たった。ユーザー判断（2026-08-20「自前実装案で進めて」）により、
既存のOpen-Meteo REST API経由の地点評価（`weather_client.get_forecast_many`、CC-BY-4.0・
GPL無関係・TTLキャッシュ/429リトライ込み）と同じ仕組みで格子点を自前サンプリングし、
フロント側でMapLibre標準のsymbolレイヤー（アイコンを独自定義、向き・長さ・色すべて
自由に設定可能）として描画する方式へ切り替えた。

T183（降水ナウキャストの延長、ユーザー要望「1時間より先も、短時間雨予報を出してほしい」
「風と同じ考え方で、風と汎用化して実装してほしい」）で、この同じ格子点マップへ`precipitation`
（降水量mm/h）を相乗りさせた。気象庁の降水ナウキャスト自体は+60分が上限（JMA提供APIの
仕様上の制約であり回避不可）のため、+60分より先はこの格子（Open-Meteo・約48時間先まで・
1時間刻み）が担う。1回のフェッチで風・降水延長予報の両方を賄うため、リクエスト数・
Open-Meteoクォータ消費を増やさない（weather_client.py: WIND_GRID_VARIABLES参照）。

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
# 変遷（2026-08-20）: 初期値0.35°（約39km間隔、56点）→ズーム13（表示範囲約15km四方）で
# 格子点が視界に1つも入らないことがあると判明し0.2°（22km、156点）へ→それでも「東京都
# 北区付近で最寄り格子点まで10.1km、ズーム13の表示半径約7.5kmを上回る」ケースが再現し、
# ユーザー要望「通常ズームでもある程度使えるように」を受けさらに密度を上げた。
# 格子間隔0.1°（緯度約11km・経度約9km）は、正方格子の最悪ケース（どの地点でも最寄り
# 格子点までの距離が対角線の半分＝約7km以内）がズーム13の表示半径にほぼ収まる値として選んだ。
#
# 地点数を増やすとGET（クエリ文字列）ではrequest-URIがnginxの既定上限を超え414 Request-URI
# Too Largeになることが実機で判明した（624地点で再現、288地点では未発生）ため、
# get_forecast_many側をPOST（フォームボディ）へ変更した（weather_client.py参照）。
# POSTなら624地点でも200 OK・約5秒で成功することを実機確認済み。1ユーザーあたりの
# Open-Meteoリクエスト回数は密度に関わらず常に1回にまとまる設計（weather_client.
# get_forecast_many）で、30分TTLキャッシュにより全ユーザーで同じ格子点を使い回すため、
# 密度を上げても429リスクは増えない（初回＝キャッシュ切れ後最初の1回のレスポンス時間が
# 伸びるだけ）。
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


# 改善計画T180: 「風の強さを面（ヒートマップ）で見たい」というユーザー要望を受け、
# 通常ズーム（13前後）でも密な表示ができる詳細格子を追加した。全域を常時この密度で
# 取得すると624点（0.1°間隔）より遥かに多くなりOpen-Meteo・自バックエンドとも負荷が増すため、
# 「表示中の範囲だけ」を対象にする。
#
# ここで最も重要な設計判断は、詳細格子の座標を「問い合わせbboxの角」からではなく
# WIND_GRID_BBOXの原点（固定）からのオフセットで計算すること。ユーザーの閲覧地点を
# そのまま格子の起点にすると、閲覧位置が1pxずれるだけで格子点の絶対座標も全部ずれてしまい、
# 近い場所を見ている別ユーザーとのキャッシュ共有（weather_client.pyのcache_key、
# 緯度経度を丸めた値がキー）が効かなくなる（＝429リスクが戻る、T178実装メモの
# 「閲覧地点中心の可変格子」問題そのもの）。原点を固定し「常に同じ絶対座標の格子点」を
# 生成することで、bboxが多少ずれていても重なる範囲では同じ座標がヒットし、
# 既存のTTLキャッシュがユーザー間で共有される。
WIND_GRID_DETAIL_SPACING_DEG = 0.02
# 1リクエストで許容する最大点数（乱用・広すぎるbboxでの過大な同時フェッチを防ぐ）。
# 0.02°間隔で1辺0.6°四方（約60km四方、ズーム10以下では通常発生しない広さ）を敷き詰めると
# 31×31=961点相当のため、余裕を持たせた上限として900点とする。
WIND_GRID_DETAIL_MAX_POINTS = 900

# ズーム依存の格子間隔（実機フィードバック「拡大率が大きいと[降水延長予報のgridFill表現の]
# 格子がゴワゴワして気になる。拡大率によって格子サイズも大きく補正する汎用的な拡張は
# できない？」）。ズームインするほど画面上に対する格子1マスの面積が広がり、gridFillの
# 色境界が段差として目立ちやすくなる。風の矢印のようにアイコンの表示サイズを大きくする
# 補正では実面積を表すgridFillには通用しない（隙間・重なりが生まれるだけ）ため、実際の
# 格子間隔自体をズームに応じて細かくする。連続的な間隔にすると閲覧者ごとに絶対座標の
# ラティスが微妙にずれてしまいキャッシュ共有（generate_wind_grid_detail_pointsのdocstring
# 参照）が効かなくなるため、離散的な段階（フロント側windLayer.ts:
# WIND_GRID_DETAIL_SPACING_STOPSと同じ値を維持すること）のみを許可する。
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
    """格子点1つぶんの時間別風向・風速・降水量。`times`はOpen-Meteoのhourly.time（Asia/Tokyo、
    forecast_days=2分＝約48時間）とインデックスが揃っている。特定時刻1点へ収束させず
    配列のまま返すのは、フロント側の時刻スライダーが追加のAPI呼び出し無しで時刻を
    切り替えられるようにするため（WeatherService.get_conditions_manyとの違い）。

    precipitation_mm（降水量、mm/h相当）はT183で追加。風の矢印と降水ナウキャストの延長
    予報（+60分以降）が同じ格子点マップを共有するため、1つのモデルへ両方を持たせている
    （モジュール冒頭のdocstring参照）。"""

    latitude: float
    longitude: float
    times: list[str]
    wind_speed_ms: list[float]
    wind_direction_deg: list[float]
    precipitation_mm: list[float]
