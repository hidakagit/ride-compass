# 静的道路属性・タイル配信（backend）

## 責務

OSM由来の道路データ（PBF取込）・警察庁事故データ・国土数値情報（指定路線）をPostGISへ
取り込み、道路の静的属性（路面・種別・指定路線・事故等）をベクタタイル（MVT）として
配信する。ルート生成とは独立した「地図を眺める」用途を支える。

**対象ファイル**

| レイヤー | ファイル |
|---|---|
| domain | `road.py`・`attributes.py`・`designation.py`・`accident.py`・`traffic.py`・`osm_adapter.py`（[region.py](routing-engine.md)は別モジュール管轄） |
| services | `tile_serving.py`・`accident_service.py`・`region_service.py`・`derived_data_freshness_service.py`（派生データ鮮度台帳、改善計画T571） |
| infrastructure | `vector_tile.py`・`tile_cache.py`・`accident_models.py`・`accident_repository.py`・`designation_models.py`・`derived_data_freshness.py`（派生データ鮮度台帳の集計クエリ、改善計画T571） |
| api | `region.py`（路面/POI/動的材料タイル・区間インスペクタ）・`accidents.py`（事故タイル）・`_tile_validation.py`・`derived_data_freshness.py`（`GET /api/admin/derived-data/freshness`、Basic認証必須、改善計画T571） |
| batch | `import_pbf.py`・`pbf_source.py`・`profile.py`・`import_accidents.py`・`import_designations.py`・`match_designations.py`・`precompute_edge_attribute_counts.py`・`precompute_way_attribute_counts.py`・`_common.py`・`refresh_derived.py` |

`api/routers/region.py`のうち`GET /api/region/dynamic-way-values/...`エンドポイントは
[動的材料・way_id値配信](dynamic-way-values.md)の管轄、`domain/road.py`の
`RoadGraphRepository`本体・`road_graph_models.py`は[ルート生成エンジン](routing-engine.md)の
管轄。本モジュールは同じ`region.py`ファイル内の路面/POI/区間インスペクタ部分と、
`vector_tile.py`・`tile_cache.py`等の周辺インフラを扱う。

## データ取込（batch）

### OSM PBF取込（`import_pbf.py`・`pbf_source.py`・`profile.py`）

```
Geofabrik/BBBike PBF抽出ファイル
        │  pbf_source.py（pyosmium、web運用にはインストールされない別依存）が1パスで
        │  全way・nodeをストリーム読み取り。producer/consumerをスレッド境界で分離
        │  （producer=osmiumのブロッキング読み取り、consumer=asyncpg COPY）
        │  profile.py（import_profile.yaml）のタグルールでway/nodeを選別
        │  タグ解釈はdomain/osm_adapter.py経由（Overpassランタイム経路と同じ意味論）
        ▼
  TEMPステージングテーブルへCOPY → INSERT ... ON CONFLICT でバルクマージ
        ▼
  osm_raw_ways / osm_raw_nodes / osm_raw_pois（PostGIS、生OSM層）
```

- `--bbox`省略時はPBF全体を取り込む。指定時は「bbox内に1つ以上のノードを持つway」が
  対象（ランタイムの`get_way_specs_with_closure`の主対象判定と同じ意味論）。POIは自身の
  座標がbbox内かで直接判定する。
- `--bbox`指定時の取込成功時のみ、その範囲の`road_graph_tiles`を「取得済み」マークする
  （`--bbox`省略時はマークしない——PBFヘッダのbboxは抽出ポリゴンの外接矩形にすぎず、
  データが無い領域を誤マークしうるため）。マーク後は`road_graph_tile_cache`（Redis
  cache-aside、[routing-engine.md](routing-engine.md)参照）も同時に温め、同じタイルの
  再importでは`is_split_up_to_date`のsplit鮮度マーカーを無効化する。
- ways/nodes/POIは1回のosmiumパスで同時に処理する（PBFの再読み込みを避ける）。node取込は
  タグを持つnodeのみ対象（大多数の形状点nodeはタグ辞書構築自体を省略）。
- 新規DB（`osm_raw_ways`が空）への初回取込のみ、`geom`列のGiSTインデックスを取込完了後まで
  構築を遅延する（逐次挿入コストの蓄積を避ける、稼働中DBの再取込ではこの分岐に入らず
  既存インデックスをそのまま使う）。
- `osm_import_runs`へrunning/succeeded/failedのステータスと実行記録を残す
  （`pbf_timestamp`＝PBFヘッダのOSMデータ鮮度、`profile_hash`＝取込プロファイルのSHA-256）。

`profile.py`は取込対象を宣言的なYAMLルール（`element_type`・`match`条件のANDマッチ・
`target`テーブル）として定義する。取込コア（`import_pbf.py`）自身はこの語彙を解釈する
だけで、新しい取込対象を増やす際はルール追加＋対応するwriter実装で行う。

### 事故データ取込（`import_accidents.py`）

警察庁交通事故統計オープンデータの本票CSV（`honhyo_{year}.csv`）を年号から組み立てた
公開URLで直接取得し、関東7都県分を`accident_points`へ取り込む。列インデックス定数
（`COL_*`）は2022年以降の68列レイアウトを前提とし、想定外の列数のCSVは行単位で
スキップせず年単位のバッチ実行自体を失敗させる（列構成の変化を「気づける形で」検知する
ため）。`accident_id`は都道府県コード・警察署等コード・本票番号・発生年の合成キー
（`domain/accident.py: build_accident_id`）で、年次再取込みでも冪等にUPSERTできる。

### 指定路線取込（`import_designations.py`）・マッチング（`match_designations.py`）

国土数値情報のN10（緊急輸送道路）・N12（重要物流道路）を都道府県別ZIPから取得し
`route_designations`へ投入する。**N10とN12はファイル形式が異なる**（N10=JPGIS/GML、
N12=素のGeoJSON）ため、`_KIND_SPECS`辞書がkindごとのURLテンプレート・source値・
ZIP内メンバー名・パーサ関数を1箇所に対応させる。冪等性は自然キーが無いため
「(kind, pref_code)単位でDELETE→INSERT」で担保し、パーサが0件を返した場合は
DELETEごとスキップする（既存データを誤って全消しする事故を防ぐ）。

`match_designations.py`が`route_designations`（線データ）を`osm_raw_ways`（全域自己完結）
へバッファマッチし、`designation_attributes`（Way派生、複合PK `(osm_way_id, kind)`）へ
書き込む事前計算バッチ。判定式・バッファ幅は`domain/designation.py`が正準。`import_
designations.py`実行後、およびOSM再取込後に再実行する必要がある。

### 事前集計バッチ（`precompute_edge_attribute_counts.py`・`precompute_way_attribute_counts.py`）

いずれも新しいSQLを書かず、`RoadGraphRepository`の既存メソッド
（`get_accident_counts`/`get_stop_poi_counts`/`get_intersection_counts`、および
`rebuild_raw_intersection_nodes`/`recompute_way_attribute_counts`）をチャンク単位で
呼び出すだけの薄いオーケストレーション。

| バッチ | 対象 | 母集団 | 実行順の依存 |
|---|---|---|---|
| `precompute_edge_attribute_counts.py` | `edge_attribute_counts`（Edge単位） | `road_edges`（ルート生成済みエリアのみ） | `precompute_road_node_degrees.py`（[routing-engine.md](routing-engine.md)）の後 |
| `precompute_way_attribute_counts.py` | `way_attribute_counts`（Way単位） | `osm_raw_ways`全域 | `rebuild_raw_intersection_nodes`をバッチ内部で先に実行 |

Way単位版は地図タイルの母集団になる（`road_edges`はルート生成済みエリアしかカバーしない
ため）。両バッチとも`source_accident_import_run_id`/`source_osm_import_run_id`
（実行時点の最新成功import run id）と`algorithm_version`（計算ロジック自体の版数、手動で
上げる）を派生データの系譜として書き込む。

### 派生データ再構築の単一エントリポイント（`refresh_derived.py`）

`presplit_road_graph.py`・`precompute_road_node_degrees.py`・
`precompute_edge_attribute_counts.py`・`precompute_elevation_attributes.py`・
`precompute_way_attribute_counts.py`・`match_designations.py`（依存DAGは
[docs/batch-pipeline-dependencies.md](../../batch-pipeline-dependencies.md)参照）を
依存順に1コマンドで実行する薄いオーケストレーション。各段は既存バッチの`run`/
`run_match`関数をそのまま呼ぶだけで新しいロジックは持たず、いずれか1段が例外を
送出したら即座に停止し後続は実行しない。`import_pbf.py`・`import_accidents.py`・
`import_designations.py`（生データ取込そのもの）は対象外。

### 派生データ鮮度台帳（`derived_data_freshness.py`・`derived_data_freshness_service.py`、
改善計画T571）

`edge_attribute_counts`・`way_attribute_counts`・`designation_attributes`が参照している
`source_*_import_run_id`（上記「事前集計バッチ」参照）を、対応する`*_import_runs`の
最新成功run（`MAX(id) WHERE status='succeeded'`）と突き合わせ、テーブルに実際反映
されている世代が古いままではないかを機械判定する（`edge_attribute_counts`/
`way_attribute_counts`は`algorithm_version`の不一致も検知）。`elevation_attributes`は
この列を持たないため（[elevation.md](elevation.md)参照）、世代比較ではなく`road_edges`
との行数差分による完成度のみを別枠で扱う。`GET /api/admin/derived-data/freshness`
（Basic認証必須）が`/admin`「鮮度」タブ（[axis-studio.md](../frontend/axis-studio.md)）へ
返す。[evaluation-scoring.md](evaluation-scoring.md)の材料欠損割合（`/admin`「材料」タブ）
とは別の切り口——材料側は完成度、本節は鮮度を見る。詳細な設計判断は
[docs/tasks/T571.md](../../tasks/T571.md)参照。

## タイル配信

### 共通骨格（`tile_serving.py: serve_cached_tile`）

`RegionService`（路面/POI）・`AccidentService`（事故）が共有する「ファイルキャッシュ確認
→ミスなら`fetch_tile`呼び出し→取得成功ならキャッシュへ書いて返す→取得不可（None）なら
空タイルを返す」という外側の骨格。取得不可の理由をどうWARNINGログへ出すかはタイル種別
ごとに異なるため、その判断は引き続き呼び出し元の`fetch_tile`側が持つ。取得不可の場合は
キャッシュへ書き込まない（後からPBF取込された際に正しいタイルを再生成できるようにする）。

### RegionService（路面・POIタイル、区間インスペクタ）

`repository`（`RoadGraphRepository`）を渡すと、要求タイルのz12祖先タイルが取得済み
マーク（`road_graph_tiles`）されていれば、MVTエンコードまで含めてPostGIS側（ST_AsMVT）
でタイルを丸ごと生成する。カバレッジ外・DB障害時、`repository`未接続時は空タイルを返す。

- **カバレッジ内と分かった時点で、そのz12祖先タイルの道路グラフ（`road_nodes`/
  `road_edges`）が未構築・古ければバックグラウンドで構築する**
  （`_maybe_trigger_graph_build`）。応答自体は待たせず即座に返し、次回以降のアクセスから
  反映される。地図を眺めるだけ（ルート生成を経ない）の利用でも道路グラフが構築される
  ようにするための機構。実際の構築（`GraphService.get_or_build_graph_with_attributes`）
  だけを`_graph_build_semaphore`（`config.py: graph_build_max_concurrent`）で絞り、安価な
  鮮度確認（`is_split_up_to_date`）は絞らない——鮮度確認と実構築を別セッションに分けて
  いるのは、1セッションを保持したままsemaphore待ちにすると密集した未構築エリアへの
  一斉アクセスでDBコネクションプールが枯渇するため。
- **タイル世代**（`ROAD_SURFACE_TILE_VERSION`・`POI_TILE_VERSION`）: MVTプロパティを
  追加・削除するたびに上げる。パスへ世代を含めることで旧世代のキャッシュ済みタイルを
  ヒットさせない。frontend側のタイルURLバージョンクエリ（`regionApi.ts`）と対で上げる
  必要があり、`export_openapi.py`が書き出す生成物とのドリフト検知テストで担保する。
- `get_axis_inspector(osm_way_id)`（区間インスペクタ）: クリックされたフィーチャーの
  `osm_way_id`で該当行を完全一致で引き直す（緯度経度からの空間マッチ最近傍だと、
  交差点付近で実際にクリックされたフィーチャーとは別の道路を拾いうるため採用しない）。
  一次属性→[評価・スコアリング](evaluation-scoring.md)の`axis_inspector_breakdown`で
  二次軸スコア・三次合成コスト（取得可能な軸だけの参考値）を返す。
- `get_material_values(material_id)`: [軸スタジオ](axis-studio.md)向けの材料値動的列挙
  （`RoadGraphRepository.get_distinct_material_values`への薄い委譲）。
- `get_accident_years_covered()`: [軸スタジオ](axis-studio.md)の`GET /api/axis-catalog`が
  地図表示の実行時スケール定数を組み立てるために使う。
- `repository`未接続・DB例外はいずれも安全側（空タイル/None/0/空リスト）へ倒す一貫した
  グレースフルデグレード方針。

### AccidentService（事故タイル）

`repository`（`AccidentTileQuery`）を渡すとPostGIS側でMVTを生成する。road_surfaceと違い
「取込範囲の一部だけ取得済み」という状態が無い（`import_accidents.py`が関東7都県を
一括で入れる）ため、カバレッジ判定は行わない。`repository`未接続・DB障害時は空タイルを
返す。

### vector_tile.py・tile_cache.py

`vector_tile.py`はMVTの共有定数（`TILE_EXTENT`・各レイヤー名）と空タイルのエンコード
関数のみを持つ（実際のMVT生成はPostGIS側のST_AsMVTが担い、Pythonでのジオメトリ
エンコードは行わない）。`tile_cache.py`はファイルベースのタイルキャッシュ（`DATA_DIR/
tile_cache/`）で、パスをSHA-256でハッシュ化したフラットなファイル名に保存する
（同じパス文字列がファイル名とディレクトリ接頭辞の両方に使われるケースでの衝突を
構造的に避けるため）。キャッシュ書き込み失敗（ディスクフル等）は握りつぶし、タイル
配信自体を失敗させない。

## API

| エンドポイント | 内容 |
|---|---|
| `GET /api/region/road-surface-tiles/{z}/{x}/{y}.pbf` | 路面・道路種別等のMVTタイル |
| `GET /api/region/poi-tiles/{z}/{x}/{y}.pbf` | 停止要因POI・補給休憩POIのMVTタイル |
| `POST /api/region/axis-inspector` | 区間インスペクタ（osm_way_id指定） |
| `GET /api/region/accident-tiles/{z}/{x}/{y}.pbf`（`accidents.py`） | 事故のMVTタイル |

MVTエンコードはPostGIS側（`ST_AsMVT`、`road_graph_repository.py`）で行う。タイル内の
wayへ付帯情報（`way_attribute_counts`・`designation_attributes`）を結合するJOINは、
wayごとの主キー検索になる形（`designation_attributes`は`LEFT JOIN LATERAL`）を保つこと——
相関の無い集約サブクエリだとテーブル全体の集約が毎タイルの固定コストになる。

**同時実行数制限**: 路面・POIタイルは`_region_tile_semaphore`
（`settings.road_tile_max_concurrent`）を共有する（DB接続プール上限を超えないため専用
semaphoreを追加しない）。事故タイルは`_accident_tile_semaphore`
（`settings.accident_tile_max_concurrent`）という別のsemaphoreを持つ。いずれも超過分は
**待たせて全件処理**する（ルート生成の即429方式とは異なる——MapLibreは失敗したタイル
要求を自動再試行しないため、429だと広範囲で一部タイルが永久に空白になりうる）。
`/health`はこれらのsemaphoreを経由しない別の同期ハンドラのため、待機中のタイル要求に
巻き込まれず応答し続ける。

応答は`ContentTypeGZipMiddleware`（[横断基盤](cross-cutting-infrastructure.md)）が
`Accept-Encoding: gzip`のクライアントへgzip圧縮して返す（MVTは約55〜60%に縮む）。
ブラウザ側HTTPキャッシュは1時間（`Cache-Control: public, max-age=3600`）。路面データは
PBF取込時にしか変わらないため、再訪時の同一タイル再取得（バーストの主成分）を省ける。

## domain層

| ファイル | 役割 |
|---|---|
| `road.py` | 路面語彙の正準定義（`GOOD_OSM_SURFACE_TAGS`/`BAD_OSM_SURFACE_TAGS`）・`classify_osm_surface`。両ルーティングエンジン・PostGIS側MVT生成SQLが共有する単一ソース |
| `attributes.py` | `ElevationAttribute`/`EdgeAttributeCounts`等のモデルと標高計算（[elevation.md](elevation.md)が主に扱う） |
| `designation.py` | 指定路線コンフレーション機構の正準定数（バッファ幅・マッチ閾値・対象kind） |
| `accident.py` | 警察庁データ取込の純関数群（都道府県コード変換・当事者種別判定・度分秒座標変換） |
| `traffic.py` | 停止要因POI・補給休憩POIの分類（`classify_stop_poi`/`classify_supply_poi`）、交差点判定の空間マッチ半径・次数しきい値 |
| `osm_adapter.py` | OSMタグ解釈（許可リストタグ・oneway方向解決等）。PBF取込・Overpassランタイム経路の両方が同じ意味論で解釈するための単一ソース |

`traffic.py: classify_stop_poi`はrailway=level_crossingとhighway系タグが同一nodeに
付く場合railway側を優先する（踏切は信号・横断歩道より自転車にとって一時停止の法的
義務が強いため）。`classify_supply_poi`はコンビニ/自販機/トイレ/給水/駐輪場を分類する
（タグ名の名前空間がstop系と独立しているため優先順位判定は不要）。

## 暗黙の前提

- **PBF取込の`--bbox`はPBFファイルが実際にカバーする範囲の内側を指定する必要がある**
  （PBFヘッダのbboxは抽出ポリゴンの外接矩形にすぎず、指定範囲がPBFの実カバー範囲を
  超えると、データが存在しない領域を「取得済み」と誤マークする）。
- **`precompute_way_attribute_counts.py`は`rebuild_raw_intersection_nodes`をバッチ内部で
  先に実行するため、`precompute_road_node_degrees.py`（Edge単位版が依存する別バッチ、
  [routing-engine.md](routing-engine.md)）とは独立した交差点情報源を持つ**——Way単位版
  （地図タイル用）とEdge単位版（評価用）は「交差点」の生成元が異なる2つの派生データ
  経路であり、片方の実行がもう片方の交差点データを更新するわけではない。
- **事故・指定路線データはPBF取込の`road_graph_tiles`カバレッジと独立**——`accident_
  points`・`route_designations`は関東7都県を一括投入するバッチのため、「取込範囲外」
  という概念自体を持たない（road_surfaceタイルとはカバレッジ判定の有無が異なる）。
- **`designation_attributes`は`osm_raw_ways`基準（road_edgesの遅延構築に依存しない）**
  ——ルート生成履歴の無いエリアでも指定路線の地図表示・評価が機能する設計。
