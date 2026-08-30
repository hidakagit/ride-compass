# ルート生成エンジン・経路探索（backend）

## 責務

出発地点（＋任意で経由地・目的地）から、周回または経由地ルートの候補を複数生成し、
距離・難易度でスコアリングして返す。実際の経路計算・軸評価は2つの差し替え可能な
エンジン（road_graph・openrouteservice）へ委譲する。Road Graph自体（ノード・Edge・
交差点分割・空間索引）の構築・永続化・キャッシュもこのモジュールが担う。

**対象ファイル**

| レイヤー | ファイル |
|---|---|
| domain | `routing.py`・`graph.py`・`route.py` |
| services | `route_generator.py`（戦略層）・`route_scorer.py`・`road_graph_engine.py`・`openrouteservice_engine.py`・`routing_service.py`・`graph_service.py` |
| infrastructure | `road_graph_models.py`・`road_graph_repository.py`（4リポジトリ）・`road_graph_tile_cache.py`・`road_edge_geometry_cache.py`・`graph_material_cache.py`・`ors_client.py` |
| api | `routes.py` |
| batch | `precompute_road_node_degrees.py` |

## エンジンの切り替え（`config.py: routing_engine`）

`Literal["road_graph", "openrouteservice"]`（既定`"road_graph"`）で切り替える。

| エンジン | 実装 | 特徴 |
|---|---|---|
| `road_graph`（既定） | `road_graph_engine.py`。自前Road Graph（DB由来のノード/Edge）+ `scipy.sparse.csgraph`のDijkstra | 標高（勾配）は事前計算済み`elevation_attributes`をキー参照するだけで組み込み済み（探索中にGSI API呼び出しは発生しない）。風は出発時点の起点付近の風をルート全体へ一様適用 |
| `openrouteservice` | `openrouteservice_engine.py`。外部ORS Directions APIへ経路計算を委譲し、評価だけ自前で行う | 区間ごとの推定到達時刻の風を使う（road_graphとは風の扱いが異なる。レスポンスの`engine`フィールドで識別可能）。路面判定はサンプル点を自前DBのEdgeへ空間マッチして行う（domain語彙はroad_graphと統一済み） |

`RouteGenerateRequest.waypoints`/`destination`（経由地・目的地指定）は**road_graph
エンジンのみ対応**（`api/routers/routes.py: generate_routes`が投稿時点で判定し、
openrouteservice選択時は400を返す）。

## 戦略層（`route_generator.py: RouteGenerator`）

エンジン非依存の周回生成戦略を1箇所に持つ。`LoopRoutingEngine`という3メソッドの契約
（Protocol、`prepare`/`trace_loop`/`evaluate_loops`）を両エンジンが実装する。

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

自前Road Graphを`GraphService`経由で取得し、`domain/routing.py`のsparse-graph Dijkstra
（`scipy.sparse.csgraph`）で探索する。

### `prepare(origin, radius_km, waypoints=None)`

対象bboxの構築方法が2パターンある:

- **bearing-based（8方位探索）**: `_bbox_around_point(origin, radius_km + マージン)`
  （円形の探索半径を包含する矩形）。
- **waypoints指定（経由地・目的地）**: `_bbox_covering_points(origin, waypoints, ...)`
  （起点＋全経由地＋目的地を包含する矩形）。

`GraphService.get_search_materials_for_bbox`でトポロジ＋5種材料（surface・
edge_attribute_counts・way_tags・elevation_attributes・designated_edge_ids）をまとめて
取得し、`_build_search_graph`で探索用グラフ（`domain/routing.py: SparseRoadGraph`、
`NodeSpatialIndex`）を構築する。データ未整備（対象タイル未取込）ならNoneを返し、
呼び出し元（`RouteGenerator`）が候補0件として扱う。

### `trace_loop` / `evaluate_loops`

`trace_loop`はDijkstraで経由地点間の最短経路（node列）を求め、`GraphService.
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
`AxisDefinition.time_scope="night_only"`を持つ軸を汎用的に判定する）。このロジックは
OpenRouteServiceEngineとroad_graph_engine.pyの両方が同じ`time_scoped_weights`関数を
呼ぶ形で共有されている。

## OpenRouteServiceEngine（`openrouteservice_engine.py`）

`RoutingService`（`ORSClient`への薄いラッパー）へ経路計算そのものを委譲し、評価
（標高・風・路面・車ストレス等）だけを自前で行う。

- **サンプリング密度**: `sample_count_for_distance(distance_km)`が距離に応じて
  約1km間隔（`SAMPLE_INTERVAL_KM=1.0`）になる点数を決め、`MIN_SAMPLE_COUNT=12`〜
  `MAX_SAMPLE_COUNT=32`でクランプする。上限32は外部API呼び出しの安全弁（標高は
  1点=GSI 1リクエストのため最悪8候補×32点=256リクエスト/生成）。
- **`_PointAttributes`（dataclass）**: surface_tag/stop_count/highway/tags/
  is_designated/intersection_count/accident_countの7属性を1つのdataclassへ束ね、
  offset簿記を`_split_by_counts`（共通ヘルパー）へ1箇所化している。`repository`
  未注入時（DBなし構成）は全属性がデフォルト値（`highway=None, tags=None`）になり
  評価自体をスキップする（`tags=None`と`tags={}`は「repository自体が無い」と
  「repositoryはあるが空間マッチが範囲外」を意図的に区別する）。
- **全候補まとめて1回のDB問い合わせ**: 路面・停止密度・車ストレス材料・交差点密度・
  事故密度のいずれも、候補ごとに分けず全候補分のサンプル点をフラット化して1回で
  `RoadGraphRepository`へ問い合わせる（`_split_by_counts`で候補単位へ復元）。
- **風のprefetch**: `gather`の前に`WindService.prefetch`で全候補分の点をまとめて
  1回先読みしキャッシュを温めておくことで、後続の候補ごとの呼び出しをキャッシュヒット
  させる（候補ごとに個別発火するとOpen-Meteoへの同時リクエストが増える）。
- **勾配は符号付き**（進行方向基準、登り=正/下り=負）。`RoadGraphEngine`の
  `ElevationAttribute.average_grade`と意味を統一する（`domain/route.py:
  RouteSegmentDetail`の正準定義）。
- **car_stress**は`car_stress_display_level(axis_difficulties.axes.get("car_stress"))`で
  公開軸`car_stress`のdifficulty(0-100)から1-5の生値へ逆変換する（road_graph_engine.pyと
  共通の関数）。

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

- `SparseRoadGraph`/`build_sparse_graph`: 並列Edge（同じnode対の重複辺）は
  コスト最小の1本を採用する（DB側の行順序に依存しない決定論的な選択）。
- `NodeSpatialIndex`/`build_node_spatial_index`/`find_nearest_node_indexed`:
  グリッドバケットによる最近傍ノード探索。
- `routable_node_ids`: 最近傍ノード探索は「ハード制約フィルタを通過したEdgeが
  最低1本残るノード」だけに制限する（制限しないと孤立ノード——幹線道路にしか面していない
  駅等——が最近傍として選ばれ、経路探索が失敗しうる）。
- `shortest_path_node_ids_sparse`/`path_to_edge_ids_sparse`/`concat_node_paths`。

### `domain/graph.py`

- `Node`/`DirectedEdge`/`RoadGraph`（Pydantic）と、`NodeLike`/`EdgeLike`/
  `RoadGraphLike`（Protocol）で構造的型付けする`LeanNode`/`LeanEdge`/`LeanRoadGraph`
  （dataclass、探索専用の高速版。Pydanticのバリデーション・内部簿記コストを避けるため
  探索フェーズに限りdataclassを使う）が並存する。
- `WaySpec`、`build_road_graph`（決定論的な内部ID生成: `osm-node-<id>`/
  `way-<id>-seg<n>-fwd/bwd`。`_split_points`が交差点/次数≥2のノードで分割する）。

### `domain/route.py`

- `Coordinates`・`RouteSegment`・`RouteSegmentDetail`（**gradient_percentは符号付きが
  正準契約**——絶対値ではない。両エンジンがこれを守り、frontend`routeStyleModes.ts`が
  この契約に依存する）・`RouteScoreComponent`・`RouteCandidate`。
- `aggregate_segments_into_bins`（500m区間ビニング）・`merge_axis_difficulties`・
  `_merge_segment_bin`。

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

いずれも**Redis自体が疎通不能ならPostGIS単独の従来動作へfail-open**する（呼び出し元は
Redis障害を意識しなくてよい）。取得済みマーカーはOverpassフォールバックを持たないため、
これを失うと該当bboxのルート生成が「データ未整備」として拒否される（再取得の自動復旧
手段が無い）——このためRedisを正本にできず、書き込みは常にPostGISが担いRedisは読み取り
高速化の派生キャッシュに留める設計になっている。

### `ors_client.py`

`httpx.AsyncClient`をコンストラクタ注入で共有する（呼び出しごとに新規生成しない）。
`x-ratelimit-remaining`ヘッダ（日次2000リクエストの無料枠残量）をログへ記録する。

## API（`api/routers/routes.py`）

| エンドポイント | 内容 |
|---|---|
| `POST /api/routes/preview` | 2点間の単純なルート取得（`RoutingService`経由の薄いラッパー。`RouteGenerator`の周回戦略は使わない） |
| `POST /api/routes/generate` | 202を即座に返す非同期ジョブ投稿。`BackgroundTasks`でジョブ本体（`_run_generate_job`）を実行 |
| `GET /api/routes/generate/{job_id}` | ジョブの状態・結果を取得（`job_registry`、サーバー再起動で失われる） |

- **同時実行数の制限**: `generate_routes`ハンドラ内で`_generate_semaphore.locked()`
  確認と`acquire()`をawaitを挟まず連続実行する（HTTPレスポンス送出という実I/Oを挟んでから
  acquireすると、複数リクエストが同時に届いた際に上限を超えて受理してしまうため）。
  セマフォの解放は`_run_generate_job`側の`finally`で行う。
- **`RoutePreferenceWeights`/`HardFilterOverride`は「上書きするなら全項目を明示する」
  方針**（`model_validator`でキー集合の完全一致を強制）。`RoutePreferenceWeights`の
  対象は`AXIS_DEFINITIONS`の公開軸のみ（内部軸は含まない）。
- ジョブ失敗時、クライアントへは汎用メッセージのみ返す: `ors_client.py`の
  `RoutingError`は外部APIの生レスポンス本文を例外メッセージに含むため、詳細は
  `logger.exception`でサーバーログにのみ残す。

## batch: `precompute_road_node_degrees.py`

`road_nodes.degree`（DB全体から見た真のグローバル次数）の事前集計バッチ。実際の集計SQL
（`_RECOMPUTE_NODE_DEGREES_SQL`）は`DerivedGraphRepository.recompute_node_degrees`が
実装済みで、本バッチはそれを呼び出すだけ。**`precompute_edge_attribute_counts.py`より
先に実行する必要がある**（`intersection_count`がこのバッチの書く`degree`列を参照する
ため）。

## 暗黙の前提のまとめ

- **road_graphとopenrouteserviceで風・夜間の評価タイミングが異なる**: road_graphは
  出発時点1点の風/昼夜判定をルート全体へ一様適用（探索中は到達時刻が未確定という制約）。
  openrouteserviceは区間ごとの推定到達時刻を使う。レスポンスの`engine`フィールドで
  どちらの定義かを判別できる。
- **`car_stress_display_level`は両エンジンが共有する**（`AXIS_DEFINITIONS["car_stress"]`を
  直接参照する関数）。
- **`GraphService`の`_repository_lock`は`get_edges_with_geometry`のみを保護する**
  ——他のメソッドは常にgather開始前の逐次実行段階でしか呼ばれないためロック不要という
  前提に立っている。新しいメソッドを`trace_loop`のgather内から呼ぶ場合はこの前提が
  崩れることに注意。
- **`graph_material_cache`はバージョン管理なし・プロセス寿命限定**——バッチ再実行後は
  プロセス再起動まで対象タイルが古い値を返す。
- **`RouteScorer`は候補1件（waypoints指定ルート）に対しては呼ばれない**——曖昧な
  「常に満点」を避けるための意図的な設計。
