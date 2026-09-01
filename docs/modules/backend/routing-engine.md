# ルート生成エンジン・経路探索（backend）

## 責務

出発地点（＋任意で経由地・目的地）から、周回または経由地ルートの候補を複数生成し、
距離・難易度でスコアリングして返す。実際の経路計算・軸評価はroad_graphエンジン
（自前Road Graph + rustworkxのlazy A*）が担う。Road Graph自体（ノード・Edge・交差点分割・
空間索引）の構築・永続化・キャッシュもこのモジュールが担う。

**対象ファイル**

| レイヤー | ファイル |
|---|---|
| domain | `routing.py`・`graph.py`・`route.py`・`geo.py`・`errors.py` |
| services | `route_generator.py`（戦略層）・`route_scorer.py`・`road_graph_engine.py`・`graph_service.py` |
| infrastructure | `road_graph_models.py`・`road_graph_repository.py`（4リポジトリ）・`road_graph_tile_cache.py`・`road_edge_geometry_cache.py`・`graph_material_cache.py`・`axis_score_cache.py` |
| api | `routes.py` |
| batch | `precompute_road_node_degrees.py`・`presplit_road_graph.py` |

road_graphエンジンは自前Road Graph（DB由来のノード/Edge）+ `rustworkx`のlazy
A*（`edge_cost_fn`コールバック、探索が実際に訪れたEdgeのみコストを計算する）で
経路計算する。標高（勾配）は事前計算済み`elevation_attributes`をキー参照するだけで
組み込み済み（探索中にGSI API呼び出しは発生しない）。風は出発時点の起点付近の風を
ルート全体へ一様適用する（探索中は到達時刻が未確定のため）。

`RouteGenerateRequest.waypoints`/`destination`（経由地・目的地指定）にも対応する
（`api/routers/routes.py: generate_routes`）。

## 戦略層（`route_generator.py: RouteGenerator`）

`LoopRoutingEngine`という3メソッドの契約（Protocol、`prepare`/`trace_loop`/
`evaluate_loops`）を挟むことで、`RouteGenerator`自体は探索エンジンの内部実装を
知らない設計になっている（将来別方式のエンジンを差し込める余地を持たせるための
抽象化）。現在の実装は`RoadGraphEngine`のみ。

```
RouteGenerator.generate_loops()
        │
        ▼
  engine.prepare(origin, radius_km, waypoints)
        │  1リクエスト分の共有準備（Road Graph構築等）。失敗時はNone→候補0件
        ▼
  8方位 × engine.trace_loop(context, waypoints, bearing)   ※asyncio.gather、return_exceptions=True
        │  RoutingErrorはその方位だけスキップ。それ以外の例外はENGINE不具合とみなしERRORログ
        ▼
  距離フィルタ（|distance - target| <= tolerance を通過した候補だけを次段へ）
        ▼
  engine.evaluate_loops(context, traced, start_time)
        │  フィルタ通過候補だけに標高・風・路面等の評価を行う
        ▼
  _with_overall_difficulty() → _with_axis_difficulties()
        │  区間segmentsから距離加重でルート単位のoverall_difficulty・axis_difficultiesを集約
        ▼
  RouteScorer.score(candidates, target_distance_km)
        ▼
  RouteCandidate一覧
```

- 8方位: 北を0として時計回り `DIRECTIONS_DEG = [0, 45, 90, 135, 180, 225, 270, 315]`。
- 半径ヒューリスティック: `RADIUS_RATIO = 1/3`（目標距離の1/3を半径とする、適応的な
  探索は行わない。実際の道路網次第で距離のばらつきが生じる）。
- `TracedLoop.bearing = None`は経由地（waypoints）指定ルートを表す（8方位探索と異なり
  「向き」を持たない。road_graph_engine.pyの逆回り候補合成をスキップする判定にも使う）。
- 候補0件になった理由は`RouteGenerator.last_no_candidates_reason`に人間可読な文字列で
  残り、`RouteGenerateResponse.no_candidates_reason`としてクライアントへ返る。

### `generate_via_waypoints`（経由地・目的地指定）

`generate_loops`とは独立した経路生成（8方位探索・距離フィルタは行わない）。
`destination`省略時は起点に戻る周回、指定時は起点に戻らず目的地で終わる片道ルート
（終点到達後に`id="route-destination"`/`direction_label="目的地ルート"`へ上書き）。
候補は常に1件のため`RouteScorer`（候補集合内min-max正規化）は呼ばない
（`total_score`は`None`のまま。frontendの`RouteList.tsx`は`total_score != null`ガードを持つ）。

## RouteScorer（`route_scorer.py`）

`score(candidates, target_distance_km)`が`ScoringWeights`（`distance_weight`・
`difficulty_weight`の2指標、`scoring.yaml`が既定値）で候補集合内の相対評価
（`total_score`）を算出する。

- 取得できなかった指標（None）は除外し、残った指標の重みだけで再正規化して合成する。
  全指標が欠損、または有効指標の重みが全て0の場合は`total_score=None`。
- `RouteCandidate.score_breakdown`（軸別の正規化スコア・重み・寄与点）も同時に付与する。
- I/Oは行わない。正規化は`score()`に渡された候補集合内でのmin-max
  （`domain/scoring.py`）のため、異なるリクエスト間のtotal_scoreは比較できない。

## RoadGraphEngine（`road_graph_engine.py`）

自前Road Graphを`GraphService`経由で取得し、`domain/routing.py`のlazy評価A*
（`rustworkx`）で探索する。Edgeコストは探索前に一括計算せず、A*が実際に訪れたEdgeに
対してのみ`edge_cost_fn`コールバックが都度呼ばれる（bbox全体[数十万Edge]のうち実際に
訪れるのはごく一部のため、事前一括計算より大幅に少ない計算量で済む）。

### `prepare(origin, radius_km, waypoints=None)`

対象bboxの構築方法が2パターンある:

- **bearing-based（8方位探索）**: `_bbox_around_point(origin, radius_km + マージン)`
  （円形の探索半径を包含する矩形）。
- **waypoints指定（経由地・目的地）**: `_bbox_covering_points(origin, waypoints, ...)`
  （起点＋全経由地＋目的地を包含する矩形）。

`GraphService.get_search_materials_for_bbox`でトポロジ＋材料（surface・
edge_attribute_counts・way_tags・elevation_attributes・designated_edge_ids、Edge単位で
`EdgeMaterialBundle`へ統合済み）をまとめて取得し、`_build_search_graph`で探索用グラフ
（`domain/routing.py: LazyRoadGraph`、`NodeSpatialIndex`）を構築する。データ未整備
（対象タイル未取込）ならNoneを返し、呼び出し元（`RouteGenerator`）が候補0件として扱う。

`_build_edge_cost_fn`が組み立てる`edge_cost_fn`は、風以外の軸別スコア（タグパース・
軸評価ループ）をEdge単位でプロセス内キャッシュする`infrastructure/axis_score_cache.py`
（`graph_material_cache`とは別枠、軸スタジオでの軸定義編集時にはこちらだけが
クリアされる）を経由する。1リクエスト内（最大24回＝8方位×3レグ）の重複計算は
`_RoadGraphContext.cost_cache`で別途防ぐ。

### `trace_loop` / `evaluate_loops`

`trace_loop`はA*で経由地点間の最短経路（node列）を求め、`GraphService.
get_edges_with_geometry`で実ジオメトリを後付けする。`evaluate_loops`が標高・風・路面・
車ストレス等の軸別difficultyを`domain/evaluation.py: compute_edge_axis_scores`で算出し、
`_build_segment_details`で`RouteSegmentDetail`列へ組み立てる。

### `_build_best_candidate`（逆回りループ候補の代数的合成）

方位ベースの周回（waypoints指定でない場合）は、順方向の探索結果から逆方向候補を
**追加のDB/API呼び出し無しに代数的に導出**する: 標高の獲得/喪失を入れ替え、勾配の符号を
反転し、既にhydrate済みのgeometryを再利用する（`_reverse_traced_edges`/
`_reverse_elevation_attribute(s)`）。両方向の`distance_weighted_difficulty`を比較し、
小さい方を採用する（`_pick_better_candidate`）。`TracedLoop.bearing is None`
（waypoints指定ルート）ではこの逆回り合成をスキップする——ユーザーが指定した訪問順序を
尊重する必要があるため。

### 夜間軸の動的重み付け

区間の推定到達時刻（風評価と同じ`arrival_time`、追加の到達時刻計算は行わない）が
その地点の市民薄明の外（`domain/twilight.is_night`）なら夜間軸の重みをそのまま、
日中なら0倍にして合成する（`domain/axis_definitions.py: time_scoped_weights`が
`AxisDefinition.time_scope="night_only"`を持つ軸を汎用的に判定する）。

## GraphService（`services/graph_service.py`）

Road Graph（Node/Edge）をPostGIS経由で取得する。**PostGISのみを参照し、Overpassへの
フォールバックは持たない**（未取込タイルは「データ未整備」としてNoneを返す）。地図表示
（`RegionService`）もタイル配信のバックグラウンドで`get_or_build_graph_with_attributes`を
呼ぶ（ルート生成した地点でしか道路グラフが構築されないと、地図を眺めるだけの利用では
road_nodes/road_edgesが空のままになるため）。

### 3段階の取得経路（`get_or_build_graph_with_attributes`）

1. **タイル未取込**: `_ensure_tiles_cached`がbboxを覆う全z12タイルの取込済みマーカー
   （`road_graph_tiles`）を1クエリで判定。1つでも未取込ならNone（WARNING常時ログ）。
2. **split鮮度が最新（省略パス）**: `_ensure_split_up_to_date`が`is_split_up_to_date`
   （生データが前回split以降変わっていないか）を確認しTrueなら、`get_graph_in_bbox`＋
   `get_surface_attributes`で直接読み出す。closure再計算・Edge全量再UPSERTを省略できる。
3. **再構築（冷パス）**: `get_way_specs_with_closure`でDB上の既知の生データ全体から
   対象Way＋近傍Wayを取得し、`build_road_graph`（純Python、CPU処理）を
   `asyncio.to_thread`で実行する（イベントループを塞がずヘルスチェック無応答を防ぐ）。
   保存は主対象Way分のみ（近傍Wayは分割の文脈情報のみで永続化しない）。ステージ別
   所要時間（closure_ms/build_ms/save_ms/total_ms）を1行INFOサマリで出す。

### タイル単位の探索用素材キャッシュ（`get_search_materials_for_bbox`）

bboxをz12タイルへ分解し、`graph_material_cache`（プロセス内LRU、上限2,000タイル）を
タイル単位で経由する。全タイルがキャッシュ済みならDBへ一切アクセスしない。split鮮度が
古い場合のみ`get_or_build_graph_with_attributes`のフル経路へフォールバックし、応答後に
バックグラウンドで該当タイルを温める（`_maybe_warm_tile_cache`）。

**暗黙の前提**: `graph_material_cache`は無効化方針として**バージョン管理を行わず
プロセス寿命でのみキャッシュする**（ユーザー承認済み）。PBF再取込や各種precomputeバッチを
実行しても、対象タイルの結果はプロセス再起動までキャッシュされた古い値のまま返る。

### `get_edges_with_geometry`の同時実行ロック

`RoadGraphEngine.trace_loop`が8方位ぶん`asyncio.gather`で並列に呼ぶため、
`GraphService.__init__`が持つ`self._repository_lock`（`asyncio.Lock`）で直列化する。
**このロックは`get_edges_with_geometry`だけに掛かる**（このメソッド以外は常に
gather開始前のprepare段階で逐次呼ばれるため対象外）。同一`AsyncSession`への同時
アクセスは未定義動作/例外を招くため。

## domain層

### `domain/routing.py`

- `LazyRoadGraph`/`build_lazy_road_graph`: 探索用グラフはトポロジのみ（Edgeコストを
  事前計算しない）。並列Edge（同じnode対の重複辺）はコストで選べないため、edge_idの
  昇順で先頭を決定論的に採用する。
- `shortest_path_node_ids_lazy`: `rustworkx.astar_shortest_path`を、探索が実際に訪れた
  Edgeに対してのみ都度呼ばれる`edge_cost_fn`コールバックでラップする。Hard Constraintで
  除外するEdgeは`edge_cost_fn`が`math.inf`を返すことで表現する（`LazyRoadGraph`自体は
  Hard Constraintを知らない）。経路確定後、合計コストが有限かを検算してから返す
  （rustworkxが`inf`を「非常に高コストだが有効」として扱い、他に経路が無ければ
  採用してしまうことがあるため）。
- `NodeSpatialIndex`/`build_node_spatial_index`/`find_nearest_node_indexed`:
  グリッドバケットによる最近傍ノード探索。
- `compute_routable_node_ids`（`domain/evaluation.py`）: 最近傍ノード探索は「0次
  ハードフィルタを通過したEdgeが最低1本残るノード」だけに制限する（制限しないと孤立
  ノード——幹線道路にしか面していない駅等——が最近傍として選ばれ、経路探索が失敗しうる）。
  lazy評価ではEdgeコストを事前計算しないため、Hard Constraintだけを軽量に評価する
  専用関数として`domain/evaluation.py`に置く（`domain/routing.py`側には持たない）。
- `path_to_edge_ids_lazy`/`concat_node_paths`。

### `domain/graph.py`

- `Node`/`DirectedEdge`/`RoadGraph`（Pydantic）と、`NodeLike`/`EdgeLike`/
  `RoadGraphLike`（Protocol）で構造的型付けする`LeanNode`/`LeanEdge`/`LeanRoadGraph`
  （dataclass、探索専用の高速版。Pydanticのバリデーション・内部簿記コストを避けるため
  探索フェーズに限りdataclassを使う）が並存する。
- `WaySpec`、`build_road_graph`（決定論的な内部ID生成: `osm-node-<id>`/
  `way-<id>-seg<n>-fwd/bwd`。`_split_points`が交差点/次数≥2のノードで分割する）。

### `domain/route.py`

- `Coordinates`・`RouteSegment`・`RouteSegmentDetail`（**gradient_percentは符号付きが
  正準契約**——絶対値ではない。frontend`routeStyleModes.ts`がこの契約に依存する）・
  `RouteScoreComponent`・`RouteCandidate`。
- `aggregate_segments_into_bins`（500m区間ビニング）・`merge_axis_difficulties`・
  `_merge_segment_bin`。

### `domain/geo.py`・`domain/errors.py`

`geo.py`は球面三角法の地理計算（`haversine_distance_km`・`bearing_between`・
`destination_point`・`compass_label`）を持つ。`LatLon`（`Protocol`）・
`LatLonPoint`（`NamedTuple`）は`Coordinates`（Pydantic、API境界の入力検証用）を経由
せずに緯度経度を扱うための軽量な構造的型で、`build_road_graph`・最近傍ノード探索のような
ホットパスがバリデーションコストを避けるために使う。`destination_point`は経度を
[-180, 180)へ正規化する（球面三角法の計算結果がこの範囲を超えうるため、正規化しないと
`Coordinates`のバリデーションが8方位分のwaypoint計算中に同期的に失敗する）。

`errors.py`は`RoutingError`（単一の例外クラス）のみを持つ。`RoadGraphEngine`・
`RouteGenerator`が経路探索の失敗を表すのに共通で使う。

## infrastructure層

### `road_graph_repository.py`（4リポジトリ構成）

変更理由が異なる操作を1クラスに同居させない設計:

| リポジトリ | 責務 | 変わる理由 |
|---|---|---|
| `RawOsmRepository` | 生OSM層（osm_raw_ways/osm_raw_nodes）・タイル取得マーカー | データ取込・closure読み出しの都合 |
| `DerivedGraphRepository` | 派生グラフ（road_nodes/road_edges）・鮮度判定（split_at） | 交差点分割アルゴリズムの都合 |
| `AttributeRepository` | Edge単位のRoad Attribute（elevation_attributes。surfaceはosm_raw_ways.surfaceをJOIN導出） | 属性の種類追加の都合 |
| `RoadSurfaceTileQuery` | 地域路面レイヤー・POI/wind/gradient配信用MVT生成（読み取り専用） | 地図表示の都合 |

`RoadGraphRepository`は4つを束ねるファサードで、**フラットな委譲メソッド群
（`repository.save_raw_ways(...)`）がサービス層が依存する正式なインターフェース**
（`repository.raw_osm.save_raw_ways(...)`という個別アクセスではない）。テストの
`FakeRoadGraphRepository`もこのフラットな形をダックタイピングで模倣する。

**トランザクション境界**: 本モジュールの書き込みメソッドは一切commitしない。
呼び出し側（サービス層）が操作のまとまりごとに`RoadGraphRepository.commit()`を呼ぶ。

#### `get_way_specs_with_closure`（タイル境界に依存しない交差点分割）

生のOSM Way/Nodeデータ（`osm_raw_ways`/`osm_raw_nodes`）は、取得元タイルに依存しない
形で蓄積される。Road Graph構築時はDB上の既知の生データ全体から必要な近傍Wayを含めて
計算し直す。**主対象Way**（bboxとST_Intersects）＋**近傍Way**（主対象Way全体のextent、
`NEIGHBOR_EXTENT_MAX_MARGIN_M=10,000m`でクランプ済み）の2段階。**既知の制約**: 近傍探索は
1ホップ相当に限定——間接的に関係するWay同士の交差点は、そのWay自身が別のリクエストで
「主対象」として処理されるまで更新されない（結果整合的）。

#### `save_graph`のCOPYベース一括UPSERT

一時テーブル経由のCOPY（バイナリプロトコル）で`road_nodes`/`road_edges`をUPSERTする
（`_copy_upsert_road_nodes`/`_copy_upsert_road_edges`）。`way_ids_to_replace`指定時の
DELETE対象抽出は、除外側集合（`new_edge_ids`）を一時テーブル化しPK索引の`NOT EXISTS`
反結合で判定する（このトランザクションだけ`work_mem`を256MBへ引き上げる`SET LOCAL`も
併用）。

**暗黙の前提**: `_asyncpg_connection`はSQLAlchemyの`AsyncSession`が「autobegin」
（何か実行するまでBEGINが送信されない）ことを踏まえ、`CREATE TEMP TABLE ... ON COMMIT
DROP`前に軽いSELECTを1つ挟んで実トランザクションを確定させる。これを省くと一時テーブルが
即座にDROPされ、直後のCOPYが失敗する。

#### 派生delivery系クエリ（wind/gradient/road surface/POI）

`_ROAD_SURFACE_TILE_MVT_SQL`（路面・道路種別・車ストレス材料タグ等をPostGIS側で
ST_AsMVT丸ごと生成）・`_WAY_IDS_IN_TILE_SQL`（wind、道路自身の方位角は使わずway_id一覧
のみ返す）・`_WAY_GRADIENT_INPUTS_IN_TILE_SQL`（gradient。wayが複数edgeに分割されている
場合はDISTINCT ONで決定論的に代表1本を選ぶ——forward/backwardのどちらを拾ってもcos補正の
結果は符号が2回反転して打ち消し合うため結果に影響しない）はいずれも同じ
「road_graph_tilesのz12祖先タイルマーク」でカバレッジ判定し、1タイル1DB往復にまとめる
設計を共有する。詳細は[dynamic-way-values.md](dynamic-way-values.md)参照。

**material_catalogの動的値列挙**（`get_distinct_material_values`）: 軸スタジオ
（AxisComposer.tsx）がhighway/surface/smoothnessのような開放的な多値材料の候補一覧を
動的取得するための経路。正規化式（`_MATERIAL_VALUE_COLUMN_EXPR`）は`_ROAD_SURFACE_TILE_
MVT_SQL`の対応する正規化式と一致させる契約（`test_road_graph_repository.py`の整合性
テストで担保）。詳細は[axis-studio.md](axis-studio.md)参照。

### `road_graph_models.py`（SQLAlchemy ORM）

主要テーブル: `osm_raw_nodes`（GiST索引なし、空間検索が一度も行われないため）、
`osm_raw_pois`（GiST索引あり、停止POI用）、`osm_raw_ways`（`split_at`列で鮮度判定、
`geom`は実体化済みLINESTRING）、`road_nodes`（`degree`列、事前集計）、`road_edges`
（`bearing_deg`列）、`elevation_attributes`、`edge_attribute_counts`（Edge単位
事前集計）、`raw_intersection_nodes`（次数3以上の生ノード）、`way_attribute_counts`
（Way単位事前集計、地図表示の母集団——`edge_attribute_counts`はルート生成済みエリア
しかカバーしないため地図表示には使えない）、`osm_import_runs`、`road_graph_tiles`
（取得済みマーカー）。

`EdgeAttributeCountsRow`/`WayAttributeCountsRow`の`source_*_import_run_id`は素の
`Integer`列で明示的な`ForeignKey()`を持たない——`ForeignKey(...)`を書くと
`Base.metadata`経由で`accident_models.py`/`road_graph_models.py`双方のimportを要求する
ようになり、`precompute_edge_attribute_counts.py`単体実行のような参照先モデルを一切
importしないプロセスで`NoReferencedTableError`を起こす。

### Redis cache-aside層（3種、いずれもPostGIS/DBが正本でfail-open設計）

| モジュール | キャッシュ対象 | TTL | 無効化 |
|---|---|---|---|
| `road_graph_tile_cache.py`（取得済みマーカー） | タイルの取込完了 | 24h | 明示的な無効化なし（一度立てば実質恒久、TTLは自己修復用） |
| `road_graph_tile_cache.py`（split鮮度マーカー） | `is_split_up_to_date`の判定結果 | 1h | `save_graph`成功直後にmark、`import_pbf.py`の再importで`invalidate_split_fresh` |
| `road_edge_geometry_cache.py` | edge_id単位の実ジオメトリ | 24h | `save_graph`が`new_edge_ids`を無条件delete（precise invalidation） |

いずれも**Redis自体が疎通不能ならPostGIS単独の動作へfail-open**する（呼び出し元は
Redis障害を意識しなくてよい）。取得済みマーカーはOverpassフォールバックを持たないため、
これを失うと該当bboxのルート生成が「データ未整備」として拒否される（再取得の自動復旧
手段が無い）——このためRedisを正本にできず、書き込みは常にPostGISが担いRedisは読み取り
高速化の派生キャッシュに留める設計になっている。

## API（`api/routers/routes.py`）

| エンドポイント | 内容 |
|---|---|
| `POST /api/routes/preview` | 2点間の単純なルート取得（`get_preview_builder`経由。`RoadGraphEngine.preview_segment`を使う。`RouteGenerator`の周回戦略は使わない） |
| `POST /api/routes/generate` | 202を即座に返す非同期ジョブ投稿。`BackgroundTasks`でジョブ本体（`_run_generate_job`）を実行 |
| `GET /api/routes/generate/{job_id}` | ジョブの状態・結果を取得（`job_registry`、サーバー再起動で失われる） |

- **同時実行数の制限**: `generate_routes`ハンドラ内で`_generate_semaphore.locked()`
  確認と`acquire()`をawaitを挟まず連続実行する（HTTPレスポンス送出という実I/Oを挟んでから
  acquireすると、複数リクエストが同時に届いた際に上限を超えて受理してしまうため）。
  セマフォの解放は`_run_generate_job`側の`finally`で行う。
- **`RoutePreferenceWeights`/`HardFilterOverride`は「上書きするなら全項目を明示する」
  方針**（`model_validator`でキー集合の完全一致を強制）。`RoutePreferenceWeights`の
  対象は`AXIS_DEFINITIONS`の公開軸のみ（内部軸は含まない）。
- ジョブ失敗時、クライアントへは汎用メッセージのみ返す: 例外の生メッセージ
  （PostGIS/内部処理のエラー詳細を含みうる）は`logger.exception`でサーバーログに
  のみ残す。

## batch: `precompute_road_node_degrees.py`

`road_nodes.degree`（DB全体から見た真のグローバル次数）の事前集計バッチ。実際の集計SQL
（`_RECOMPUTE_NODE_DEGREES_SQL`）は`DerivedGraphRepository.recompute_node_degrees`が
実装済みで、本バッチはそれを呼び出すだけ。**`precompute_edge_attribute_counts.py`より
先に実行する必要がある**（`intersection_count`がこのバッチの書く`degree`列を参照する
ため）。

## batch: `presplit_road_graph.py`

取込済み全z12タイル（`road_graph_tiles`）を走査し、`is_split_up_to_date`が偽なタイルへ
`GraphService.get_or_build_graph_with_attributes`（実行時の遅延構築と同じ再構築経路）を
順に適用する。新しい分割ロジックは持たず既存メソッドを呼ぶだけで、split済みタイルは
スキップして冪等。タイルごとに新規DBセッションを開き1件ずつ処理する（並列化しない）。
このバッチが処理中のタイルへ実行時の遅延構築が同時に到達すると、両者は独立に
同じ`closure取得→build_road_graph→save_graph`を実行し、`road_edges`の行ロックで
一方が他方の完了を待つ（edge_idが決定論的なため最終的には同じ結果へ収束する）。

## 暗黙の前提のまとめ

- **風・夜間の評価は出発時点1点で決まる**: 探索中は到達時刻が未確定という制約のため、
  出発時点の起点付近の風/昼夜判定をルート全体へ一様適用する（区間ごとの推定到達時刻は
  使わない）。
- **`GraphService`の`_repository_lock`は`get_edges_with_geometry`のみを保護する**
  ——他のメソッドは常にgather開始前の逐次実行段階でしか呼ばれないためロック不要という
  前提に立っている。新しいメソッドを`trace_loop`のgather内から呼ぶ場合はこの前提が
  崩れることに注意。
- **`graph_material_cache`はバージョン管理なし・プロセス寿命限定**——バッチ再実行後は
  プロセス再起動まで対象タイルが古い値を返す。
- **`axis_score_cache`（Edge単位の静的軸別スコア）は`graph_material_cache`とは別枠**
  ——軸スタジオでの軸定義編集（`AxisRegistryAdminService`→`refresh_axis_definitions`）
  はこちらだけをクリアし、材料キャッシュ（DBアクセスを伴う取得）は温存する。編集直後の
  最初のリクエストがDBへ再問い合わせせずに済む設計上の分離。
- **`RouteScorer`は候補1件（waypoints指定ルート）に対しては呼ばれない**——曖昧な
  「常に満点」を避けるための意図的な設計。
