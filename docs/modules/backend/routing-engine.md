# ルート生成エンジン・経路探索（backend）

## 責務

出発地点（＋任意で経由地・目的地）から、周回または経由地ルートの候補を複数生成し、
距離・難易度でスコアリングして返す。実際の経路計算・軸評価は2つの差し替え可能な
エンジン（road_graph・openrouteservice）へ委譲する。

**対象ファイル**

| レイヤー | ファイル |
|---|---|
| domain | `routing.py`・`graph.py`・`route.py` |
| services | `route_generator.py`（戦略層）・`route_scorer.py`・`road_graph_engine.py`・`openrouteservice_engine.py`・`routing_service.py`・`graph_service.py` |
| infrastructure | `road_graph_models.py`・`road_graph_repository.py`・`road_graph_tile_cache.py`・`road_edge_geometry_cache.py`・`graph_material_cache.py`・`ors_client.py` |
| api | `routes.py` |
| batch | `precompute_road_node_degrees.py` |

## エンジンの切り替え（`config.py: routing_engine`）

`Literal["road_graph", "openrouteservice"]`（既定`"road_graph"`）で切り替える。

| エンジン | 実装 | 特徴 |
|---|---|---|
| `road_graph`（既定） | `road_graph_engine.py`。自前Road Graph（DB由来のノード/Edge）+ `scipy.sparse.csgraph`のDijkstra | 標高（勾配）は事前計算済み`elevation_attributes`をキー参照するだけで組み込み済み（探索中にGSI API呼び出しは発生しない）。風は出発時点の起点付近の風をルート全体へ一様適用 |
| `openrouteservice` | `openrouteservice_engine.py`。外部ORSサービスへ委譲 | 区間ごとの推定到達時刻の風を使う（road_graphとは風の扱いが異なる。レスポンスの`engine`フィールドで識別可能） |

`RouteGenerateRequest.waypoints`/`destination`（経由地・目的地指定）は**road_graph
エンジンのみ対応**（`api/routers/routes.py: generate_routes`が投稿時点で判定し、
openrouteservice選択時は400を返す）。

## 戦略層（`route_generator.py: RouteGenerator`）

エンジン非依存の周回生成戦略を1箇所に持つ。`LoopRoutingEngine`という3メソッドの契約
（Protocol）を両エンジンが実装する。

```
RouteGenerator.generate_loops()
        │
        ▼
  engine.prepare(origin, radius_km, waypoints)
        │  1リクエスト分の共有準備（Road Graph構築等）。失敗時はNone→候補0件
        ▼
  8方位 × engine.trace_loop(context, waypoints, bearing)
        │  1方位分の周回経路。失敗はRoutingError（その方位はスキップ）
        ▼
  距離フィルタ（目標距離の許容範囲を通過した候補だけを次段へ）
        │
        ▼
  engine.evaluate_loops(context, traced, start_time)
        │  フィルタ通過候補だけに標高・風・路面等の評価を行う
        │  （棄却済み候補に外部API問い合わせを浪費しないための2段階分割）
        ▼
  RouteScorer.score(candidates, target_distance_km)
        │  距離・難易度からtotal_scoreを付けて並べ替え
        ▼
  RouteCandidate一覧
```

- 8方位: 北を0として時計回り `[0, 45, 90, 135, 180, 225, 270, 315]`。
- 半径ヒューリスティック: `RADIUS_RATIO = 1/3`（目標距離の1/3を半径とする、適応的な
  探索は行わない）。
- `TracedLoop.bearing = None`は経由地（waypoints）指定ルートを表す（8方位探索と異なり
  「向き」を持たない）。

## RouteScorer（`route_scorer.py`）

`score(candidates, target_distance_km)`が`ScoringWeights`（`distance_weight`・
`difficulty_weight`の2指標、`api/routers/routes.py`参照）で候補集合内の相対評価
（`total_score`）を算出する。全指標の重みを0にすると`total_score=None`（合成不能）。

## API（`api/routers/routes.py`）

| エンドポイント | 内容 |
|---|---|
| `POST /api/routes/preview` | 2点間の単純なルート取得（`RoutingService`経由、ORSクライアントへの薄いラッパー。`RouteGenerator`の周回戦略は使わない） |
| `POST /api/routes/generate` | 202を即座に返す非同期ジョブ投稿。`BackgroundTasks`でジョブ本体（`_run_generate_job`）を実行 |
| `GET /api/routes/generate/{job_id}` | ジョブの状態・結果を取得（`job_registry`、サーバー再起動で失われる） |

`generate_routes`は同時実行数を`asyncio.Semaphore`で制限し、上限到達時は即座に429を
返す（`locked()`確認と`acquire()`をawaitを挟まず連続実行することで、確認から実際の
取得までの間に他リクエストが割り込むレースを防いでいる）。
