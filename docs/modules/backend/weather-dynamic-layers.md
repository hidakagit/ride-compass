# 気象・動的レイヤー（backend）

## 責務

Open-Meteo（気象一般・風グリッド）・気象庁（アメダス・警報/注意報・タイル系ナウキャスト・
WBGT・洪水予報）由来のデータを取得・キャッシュし、地点の天候・警報・地図タイルとして
配信する。

**対象ファイル**

| レイヤー | ファイル |
|---|---|
| domain | `weather.py`・`jma_amedas.py`・`jma_area.py`・`jma_warning.py`・`wbgt.py`・`wbgt_points.py`・`twilight.py`・`night.py`・`flood_forecast.py` |
| services | `weather_service.py`・`jma_amedas_service.py`・`wbgt_service.py`・`warning_service.py`・`flood_service.py` |
| infrastructure | `weather_client.py`・`jma_tile_client.py`・`jma_amedas_client.py`・`jma_warning_client.py`・`wbgt_client.py`・`flood_client.py`・`basemap_client.py` |
| api | `weather.py`・`jma_tile.py`・`basemap.py` |

## API（`api/routers/weather.py`）

| エンドポイント | データ源 |
|---|---|
| `GET /api/weather` | Open-Meteo（現在の天候） |
| `GET /api/weather/warnings` | 気象庁警報・注意報 |
| `GET /api/weather/wbgt` | 環境省WBGT |
| `GET /api/weather/flood-forecast` | 河川洪水予報 |
| `GET /api/weather/amedas` | 気象庁アメダス実測値 |
| `GET /api/weather/wind-grid`・`/wind-grid-detail` | Open-Meteo風グリッド |

## JMAタイル系の共通プロキシ（`api/routers/jma_tile.py`）

`GET /api/jma-tile/{path:path}` が降水ナウキャスト・rasrf・雷/竜巻ナウキャスト・
キキクル・線状降水帯予測マップなど、気象庁のタイル系データを**すべて1つの汎用プロキシ**
で中継する（`path`をそのまま気象庁側へ引き渡す）。レート制限のみを課し、認証は無し
（気象庁タイル自体が公開データのため）。`basemap.py`（基礎地図タイルのプロキシ+
キャッシュ）と同じ方針。

## 天候取得の2つの経路（`weather_service.py: WeatherService`）

`WeatherService`のdocstringが明記する設計:

| メソッド | 用途 | 時刻 |
|---|---|---|
| `get_conditions(point)` | 天気APIエンドポイント・`RoadGraphEngine`の起点判定 | 常に現在時刻 |
| `get_conditions_many(...)` | `WindService`向け、複数地点・複数時刻をまとめて解決 | ルート上の各点＋推定到達時刻（未来時刻） |

## その他のサービス

- `JmaAmedasService`: 最寄りのアメダス観測所（`_nearest_station`）を選び、Redisへ
  キャッシュ（`_redis_key`）。
- `WarningService`: 気象庁警報・注意報XML/JSONを地域コード（`ResolvedArea`）で解決。
- `WbgtService`: 環境省WBGT予報から最も近い時刻の値を選ぶ（`_pick_nearest_forecast`）。
- `FloodService`: 河川洪水予報。
