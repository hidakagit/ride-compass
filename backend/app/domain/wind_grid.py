"""風の格子点マップ（改善計画T178フォローアップ）。

`@openmeteo/weather-map-layer`（GPLv2、内部の.omファイルデコーダ@openmeteo/file-reader等も
同じくGPL-2.0-only）を使った気象庁MSM由来の風矢印描画は、(1) GPLv2依存が避けられない、
(2) 矢印の長さがライブラリ側でズームレベル依存に固定され自由に表現できない、という
2つの制約に実機で行き当たった。ユーザー判断（2026-08-20「自前実装案で進めて」）により、
既存のOpen-Meteo REST API経由の地点評価（`weather_client.get_forecast_many`、CC-BY-4.0・
GPL無関係・TTLキャッシュ/429リトライ込み）と同じ仕組みで格子点を自前サンプリングし、
フロント側でMapLibre標準のsymbolレイヤー（矢印アイコンを独自定義、向き・長さ・色すべて
自由に設定可能）として描画する方式へ切り替えた。

このモジュール自体はexternal APIを叩かない純粋な座標生成のみを持つ（フェッチは
services/weather_service.pyのget_wind_grid、APIエンドポイントはapi/routers/weather.py）。
"""

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


class WindGridPoint(BaseModel):
    """格子点1つぶんの時間別風向・風速。`times`はOpen-Meteoのhourly.time（Asia/Tokyo、
    forecast_days=2分＝約48時間）とインデックスが揃っている。特定時刻1点へ収束させず
    配列のまま返すのは、フロント側の時刻スライダーが追加のAPI呼び出し無しで時刻を
    切り替えられるようにするため（WeatherService.get_conditions_manyとの違い）。"""

    latitude: float
    longitude: float
    times: list[str]
    wind_speed_ms: list[float]
    wind_direction_deg: list[float]
