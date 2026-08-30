# 標高（backend）

## 責務

国土地理院DEMタイルから標高を取得し、Road GraphのEdge単位属性（勾配計算の入力）へ
供給する。

**対象ファイル**

| レイヤー | ファイル |
|---|---|
| domain | `attributes.py`（`ElevationAttribute`・`compute_elevation_attribute`） |
| services | `elevation_aggregation.py`・`elevation_attribute_service.py` |
| infrastructure | `elevation_client.py` |
| batch | `precompute_elevation_attributes.py` |

`api/dependencies.py`の`get_elevation_attribute_service`、
`infrastructure/road_graph_repository.py: AttributeRepository.get_elevation_attributes`/
`save_elevation_attributes`は[routing-engine.md](routing-engine.md)が主管するファイルに
属するため対象表には加えず参照のみ行う。

## ElevationAttributeService（`elevation_attribute_service.py`）

Road GraphのDirected Edgeへ標高属性（`ElevationAttribute`）を紐付ける。Edgeの形状点
（geometry）を国土地理院APIへ問い合わせ、計算ロジック自体はdomain層（`domain/
attributes.py: compute_elevation_attribute`）に委譲する。`MAX_CONCURRENT_REQUESTS = 5`
で`ElevationClient`への同時リクエスト数を制限する。

`ElevationAttributeService.get_attributes_for_graph`が返す標高属性（`elevation_gain_m`・
`min_elevation_m`・`max_elevation_m`・`max_gradient_percent`）の最終集約（合計/最小/最大・
空ならNone・小数1桁丸め）は`elevation_aggregation.py`（`sum_or_none`・`min_or_none`・
`max_or_none`）に集約されており、`RoadGraphEngine._aggregate_elevation`
（[routing-engine.md](routing-engine.md)）がEdge単位の標高属性をルート単位へ集約する
際にこれを使う。

## DEMタイル方式（`infrastructure/elevation_client.py`）

GSIのDEMタイル（テキスト形式、256行×256列カンマ区切り、欠測は`"e"`）を範囲ごと取得し
ローカルで双線形補間（`_bilinear_interpolate`）する。呼び出し側インターフェースは
`get_elevation(client, point, refresh=False)`。

`type`は単一のDEM種別ではなく`DEM_TYPE_PRIORITY = ("dem5a", "dem5b", "dem5c", "dem")`
（優先順位付き複数種別）をタイル単位でクライアント側から順に試す。全種別を
`DEM_ZOOM=14`固定で扱う。

一時的な通信エラーと恒久的なカバレッジ外（404）は`_CoverageGap`センチネルで区別し、
恒久的な欠損のみを`_tile_grid_cache`（プロセス内メモリ）へ永続的にキャッシュする
（通信エラーは永続キャッシュしない）。

キャッシュは2段: 生タイル本文は`tile_cache.py`（ファイルキャッシュ、TTLなし。DEMは不変
データのため）。パース済みグリッド（256×256の`float|None`二次元配列）はさらにプロセス内
メモリ（`_tile_grid_cache`）にも保持し、1リクエスト内で近接する複数のサンプル点が同じ
タイルを共有する場合にファイル読み出し・パースを都度繰り返さないようにする。サイズ上限は
設けていない。

## 事前計算バッチ（`batch/precompute_elevation_attributes.py`）

Road Graphの全Edgeに対して`ElevationAttributeService`をあらかじめ実行し、
`elevation_attributes`テーブルへ永続化する。実際の計算ロジックは本バッチが独自に持つ
のではなく`ElevationAttributeService.get_attributes_for_graph`をそのまま呼ぶ。
`CHUNK_SIZE = 2_000`。

`ElevationAttributeService`は`repository`を渡すと、Edgeごとに先にPostGISで既存の
Attributeを確認し（`get_elevation_attributes`）、既に永続化済みならGSIへ問い合わせない
——本バッチは再実行しても未計算分だけを埋める形で安全に再実行できる。

**暗黙の前提（モジュール間の隠れた依存）**: このバッチが対象Edgeに対して実行されて
いない、または`elevation_attributes.average_grade`がNULLのままだと、
[dynamic-way-values.md](dynamic-way-values.md)の勾配材料配信（`GradientWayService`・
`get_way_gradient_inputs_in_tile`）はそのway_idを結果から黙って除外する（SQL側の
`ea.average_grade IS NOT NULL`条件）。[routing-engine.md](routing-engine.md)のroad_graph
エンジンの探索コスト側も同様に「未計算のEdgeはNoneのまま＝評価スキップ」として扱う。
このバッチの実行状態は、実行が漏れていても即座にはエラーとして顕在化せず、地図上の
一部道路の勾配色・車ストレス評価が静かに欠落するという性質の障害モードを持つ。

**同時実行制御**: `ElevationAttributeService`は、`repository`が内包するSQLAlchemyの
`AsyncSession`が複数コルーチンからの同時使用不可であることを踏まえ、
`self._repository_lock`（`asyncio.Lock`）でrepositoryアクセスだけを直列化する。これは
`RoadGraphEngine.evaluate_loops`が候補（方位）ごとに`asyncio.gather`で並列に本サービスを
呼ぶために必要な保護。GSIへのHTTP問い合わせ（`_get_attribute`）自体はロック外で並列に
走る（`self._semaphore`のみで制限）。

`repository`指定時のもう一つの前提: `elevation_attributes`テーブルは
`road_edges.edge_id`への外部キー（ON DELETE CASCADE）を持つため、渡す`graph`は事前に
同じ`repository`経由でDBへ保存済み（`road_edges`にそのedge_idの行が存在する状態）で
なければならない。DB未保存のRoadGraphを`repository`指定時に渡すと
`save_elevation_attributes`が外部キー制約違反で失敗する。

## データフロー図

```
[バッチ事前計算＋探索時参照]
precompute_elevation_attributes.py（オフライン、CHUNK_SIZE=2000）
  → RoadGraphRepository.get_edges_with_geometry
  → ElevationAttributeService.get_attributes_for_graph
       → repository.get_elevation_attributes（既存分をスキップ）
       → 未計算分のみ ElevationClient.get_elevation を並列取得
       → domain/attributes.py: compute_elevation_attribute で ElevationAttribute 算出
       → repository.save_elevation_attributes → repository.commit（サービス層がcommit）
  → elevation_attributes テーブルへ永続化
       │
       ├─→ RoadGraphEngine.prepare 時に読み取り専用でキー参照（探索コスト・axis_difficulties）
       └─→ dynamic-way-values.md: GradientWayService が average_grade + road_edges.bearing_deg
            をJOINして勾配材料を配信（未計算Edgeは静かに除外）

[ElevationClientの内部]
get_elevation(point) → DEM_TYPE_PRIORITY順にタイル取得
  → tile_cache（ファイル、無期限）→ ミス時GSI DEMタイルHTTP取得
  → _tile_grid_cache（プロセス内メモリ、恒久キャッシュは404[_CoverageGap]のみ）
  → _bilinear_interpolate で任意地点の標高を補間
```
