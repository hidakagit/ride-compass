# 静的道路属性・タイル配信（backend）

## 責務

OSM由来の道路データ（PBF/Overpass）をPostGISへ取り込み、道路の静的属性（路面・
種別・指定路線等）と事故データをベクタタイル（MVT）として配信する。

**対象ファイル**

| レイヤー | ファイル |
|---|---|
| domain | `road.py`・`attributes.py`・`designation.py`・`accident.py`・`traffic.py` |
| services | `tile_serving.py`・`accident_service.py`・`region_service.py`（一部、道路タイル取得） |
| infrastructure | `vector_tile.py`・`tile_cache.py`・`accident_models.py`・`accident_repository.py`・`designation_models.py` |
| api | `region.py`（路面/POIタイル）・`accidents.py`（事故タイル） |
| batch | `import_pbf.py`・`pbf_source.py`・`import_accidents.py`・`import_designations.py`・`match_designations.py`・`precompute_edge_attribute_counts.py`・`precompute_way_attribute_counts.py`・`profile.py`・`_common.py` |

## データ取込（batch）

```
Geofabrik/BBBike PBF抽出ファイル
        │  import_pbf.py（import_profile.yamlでタグをマッチ）
        │  タグ解釈はdomain/osm_adapter.py経由（Overpassランタイム経路と同じ意味論）
        ▼
  osm_raw_ways / osm_raw_nodes（PostGIS、生OSM層）
```

- `--bbox`省略時はPBF全体を取り込む。指定時は「bbox内に1つ以上のノードを持つway」が対象
  （ランタイムのOverpass経路と同じ判定）。
- `--bbox`を指定した取込成功時、その範囲の`road_graph_tiles`を「取得済み」マークする
  （以後`GraphService`がその範囲でOverpassへ行かなくなる）。**`--bbox`はPBFが実際に
  カバーする範囲の内側を指定すること**（PBFヘッダのbboxは抽出ポリゴンの外接矩形に
  すぎないため）。
- 事故（`import_accidents.py`）・指定路線（`import_designations.py`・
  `match_designations.py`）は別バッチ。

## タイル配信（api/region.py・accidents.py）

| エンドポイント | 内容 |
|---|---|
| `GET /api/region/road-surface-tiles/{z}/{x}/{y}.pbf` | 路面・道路種別等のMVTタイル |
| `GET /api/region/poi-tiles/{z}/{x}/{y}.pbf` | 停止要因POI（信号・横断歩道等）のMVTタイル |
| `GET /api/region/accident-tiles/{z}/{x}/{y}.pbf`（`accidents.py`） | 事故のMVTタイル |

MVTエンコードはPostGIS側（`ST_AsMVT`、`road_graph_repository.py`）で行う（Python側での
逐次エンコードは過去の実装で、密集タイルで約7.6秒かかっていた経緯がある）。

**同時実行数制限**: `_region_tile_semaphore`（`settings.road_tile_max_concurrent`）を
路面・POIタイルが共有する（DB接続プール上限を超えないため専用semaphoreを追加しない）。
超過分は**待たせて全件処理**する（ルート生成の即429方式とは異なる——MapLibreは失敗した
タイル要求を自動再試行しないため、429だと広範囲で一部タイルが永久に空白になる不具合が
実機で発生した経緯がある）。

ブラウザ側HTTPキャッシュは1時間（`Cache-Control: public, max-age=3600`）。路面データは
PBF取込時にしか変わらないため、再訪時の同一タイル再取得（バーストの主成分）を省ける。
