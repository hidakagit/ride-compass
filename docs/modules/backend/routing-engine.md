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
| services | `route_generator.py`（戦略層）・`road_graph_engine.py`・`graph_service.py` |
| infrastructure | `road_graph_models.py`・`road_graph_repository.py`（4リポジトリ）・`road_graph_tile_cache.py`・`road_edge_geometry_cache.py`・`graph_material_cache.py`・`tile_score_matrix_cache.py`・`search_graph_cache.py`・`tile_persistent_cache.py`・`osm_way_tag_sql.py`（`osm_raw_ways`のOSMタグ分類SQL断片の単一の情報源、[evaluation-scoring.md](evaluation-scoring.md)の`material_coverage.py`と共有） |
| api | `routes.py` |
| batch | `precompute_road_node_degrees.py`・`presplit_road_graph.py` |

road_graphエンジンは自前Road Graph（DB由来のノード/Edge）+ `rustworkx`のA*で経路計算する。
Edgeコストは「タイル単位の静的Edge×公開軸スコア行列＋リクエスト時ベクトル計算」方式で
算出する——探索が実際に訪れたEdgeに対してPythonのコスト計算コールバックを都度呼ぶのでは
なく、`prepare`/`preview_segment`が対象bbox全体ぶんの
コスト配列を1回だけnumpyで合成し、A*（`domain/routing.py: shortest_path_node_ids_lazy`）
へは合成済み配列への`list.__getitem__`だけを渡す（探索中にPythonの関数フレームを作らない）。
標高（勾配）は事前計算済み`elevation_attributes`をキー参照するだけで組み込み済み
（探索中にGSI API呼び出しは発生しない）。風は出発時点の起点付近の風をルート全体へ
一様適用する（探索中は到達時刻が未確定のため）。

`RouteGenerateRequest.waypoints`/`destination`（経由地・目的地指定）にも対応する
（`api/routers/routes.py: generate_routes`）。

## 戦略層（`route_generator.py: RouteGenerator`）

`LoopRoutingEngine`という7メソッドの契約（Protocol、`prepare`/`select_loop_turnarounds`/
`trace_loop_from_turnaround`/`select_via_nodes`/`trace_loop`/`evaluate_loops`/
`is_loop_too_similar`）を挟むことで、`RouteGenerator`自体は探索エンジンの内部実装を
知らない設計になっている（将来別方式のエンジンを差し込める余地を持たせるための抽象化）。
現在の実装は`RoadGraphEngine`のみ。

候補の形は公開軸の重み配分で決まる（フロンティア方式）:
起点からの一対全最短経路木（軸重み付きコスト）で目標距離の半分付近に到達する折返し点を
往路の軸的な良さの順に選び、往路と別の復路を探索して周回にする。距離は目標
±`distance_tolerance_km`の厳格フィルタで、スコアとは混ぜない。

```
RouteGenerator.generate_loops(origin, distance_km, distance_tolerance_km, max_routes)
        │
        ▼
  engine.prepare(origin, radius_km)
        │  1リクエスト分の共有準備（Road Graph構築等）。失敗時はNone→候補0件
        ▼
  engine.select_loop_turnarounds(context, distance_km, distance_tolerance_km, pool_size)
        │  折返し点候補を、往路の軸的な良さの順に最大pool_size件（互いに似た往路は
        │  間引き済み）返す。空なら候補0件
        ▼
  ランク順に逐次: engine.trace_loop_from_turnaround(context, turnaround)
        │  往路（木の経路そのもの）＋往路と別の復路（A*）で周回を1本組み立てる。
        │  RoutingErrorはその候補だけスキップ、距離フィルタ不合格も同様にスキップ。
        │  engine.is_loop_too_similar(context, candidate, accepted)が採用済み候補と
        │  周回全体（往路＋復路、進行方向無視）で重複しすぎると判定した候補もスキップ
        │  （「同じ周回の逆回り」等を弾く）。このチェックを通過した候補数が
        │  max_routes件に達した時点で処理を打ち切る
        ▼
  engine.evaluate_loops(context, traced, start_time)
        │  フィルタ通過候補だけに実ジオメトリ取得・標高・風・路面等の評価を行う
        ▼
  _with_overall_difficulty() → _with_axis_difficulties() → _with_axis_contributions()
        │  区間segmentsから距離加重でルート単位のoverall_difficulty・
        │  axis_difficulties・axis_contributionsを集約
        ▼
  candidates.sort(overall_difficulty昇順[小数1桁]、同点は目標距離に近い順、Noneは末尾)
        │  先頭max_routes件へスライスし、idをroute-00..へ振り直す
        ▼
  RouteCandidate一覧
```

- 半径ヒューリスティック: `TURNAROUND_RADIUS_RATIO = 0.4`（目標距離に対する比率。
  折返し点は往路の実距離が目標の半分付近にあり、直線距離はそれより短い[実道路の迂回率は
  概ね1.3]ため、0.5ではなく0.4から始める。半径不足時は一対全探索がbboxで自然に切れ
  リング[折返し候補の集合]が欠けるだけで壊れない）。
- 候補数: `RouteGenerateRequest.max_routes`（`ge=1, le=MAX_ROUTES`[15],
  `default=DEFAULT_MAX_ROUTES`[8]）。折返し点候補プールのサイズは
  `turnaround_pool_size(max_routes)`（`min(40, max(12, max_routes*3))`）。
- `LoopTurnaround`: `bearing`（起点から見た折返し点の方位、表示ラベル用のみ）・
  `outbound_difficulty`（往路の距離加重平均difficulty、ランキング指標）・`data`
  （エンジン固有、復路探索に使う。road_graphエンジンでは往路の実距離[m]も
  `data.outbound_length_m`として持つ）。
- `TracedLoop.bearing = None`は経由地（waypoints）指定ルートを表す（周回候補と異なり
  「向き」を持たない。road_graph_engine.pyの逆回り候補合成をスキップする判定にも使う）。
- 候補は折返し点候補のランク順に逐次処理する（復路探索が共有`cost_list`を一時的に
  書き換える同期処理のため`asyncio.gather`による並列化の余地は無い）。距離フィルタ合格が
  `max_routes`件に達した時点で処理を打ち切る。
- 候補0件になった理由は`RouteGenerator.last_no_candidates_reason`に人間可読な文字列で
  残り、`RouteGenerateResponse.no_candidates_reason`としてクライアントへ返る。

### `generate_via_waypoints`（経由地・目的地指定）

`generate_loops`の折返し点選定・距離フィルタとは独立した経路生成。
`destination`省略時は起点に戻る周回（常に1件）。

`destination`指定時は、経由地の有無で分岐する（[T551](../../tasks/T551.md)）:

- **経由地が無い（起点→目的地のみ）**: `_generate_destination_routes`が
  `engine.select_via_nodes`（via-node方式、後述）で`max_routes`件まで互いに異なる
  代替経路を生成する。`overall_difficulty`昇順（`generate_loops`と同じ規約）で
  `id="route-destination-00"`形式へ振り直し、`direction_label="目的地ルート"`を
  全件に付ける。
- **経由地が1つ以上ある**: レグごとに代替案が組合せで増えるためv1では対象にせず、
  従来どおり`trace_loop`で単一経路を生成する（`max_routes`は無視される。終点到達後に
  `id="route-destination"`/`direction_label="目的地ルート"`へ上書き、id採番はしない）。

## 候補タブの並び順

`generate_loops`・`generate_via_waypoints`（経由地の無い目的地ルートを含む）とも、
返す`RouteCandidate`一覧を`overall_difficulty`（絶対基準0-100の総合難易度、小数1桁で
比較）昇順（易しい候補が先頭）で並べる。算出不能（`None`）の候補は末尾へ回す。
`generate_loops`は同点（小数1桁が一致）の候補を、評価前に付けた「目標距離に近い順」を
安定ソートで引き継いで並べる——周囲に重みを振った軸のデータが無く全候補のdifficultyが
同じ値になる場合、結果は実質的に目標距離に近い順になる。異なるリクエスト間でも同じ
絶対基準で比較できる。

`generate_loops`は先頭`max_routes`件へスライスした後、idを`route-00..`へ振り直す
（同じ方位に複数候補が並びうるため方位由来のidは一意にならない。`direction_label`は
エンジンが方位から付けた表示用ラベルのまま）。経由地の無い目的地ルート
（[T551](../../tasks/T551.md)）も同じ規約でidを`route-destination-00..`へ振り直すが、
「目標距離」という概念自体が無いため同点タイブレークは持たない（`select_via_nodes`の
`select_diverse_by_overlap`が既に決定的な順序で候補を返す）。

## RoadGraphEngine（`road_graph_engine.py`）

自前Road Graphを`GraphService`経由で取得し、`domain/routing.py`のlazy評価A*
（`rustworkx`）で探索する。Edgeコストは探索前に一括計算せず、A*が実際に訪れたEdgeに
対してのみ`edge_cost_fn`コールバックが都度呼ばれる（bbox全体[数十万Edge]のうち実際に
訪れるのはごく一部のため、事前一括計算より大幅に少ない計算量で済む）。周回候補は
`select_loop_turnarounds`（起点からの一対全最短経路木で折返し点を選ぶ）＋
`trace_loop_from_turnaround`（往路＋復路A*）が担い、経由地・目的地指定ルートは
`trace_loop`が指定地点列を順にA*で結ぶ。

### `prepare(origin, radius_km, waypoints=None)`

対象bboxの構築方法が2パターンある:

- **周回探索（折返し点方式）**: `_bbox_around_point(origin, radius_km + マージン)`
  （円形の探索半径を包含する矩形、`radius_km = distance_km × TURNAROUND_RADIUS_RATIO`）。
- **waypoints指定（経由地・目的地）**: `_bbox_covering_points(origin, waypoints, ...)`
  （起点＋全経由地＋目的地を包含する矩形）。

`GraphService.get_search_materials_for_bbox`でトポロジ＋材料（surface・
edge_attribute_counts・way_tags・elevation_attributes・designated_edge_ids、Edge単位で
`EdgeMaterialBundle`へ統合済み）＋`StaticEdgeScoreMatrix`（タイル単位で
キャッシュ済みの「Edge×公開軸」静的スコア行列）をまとめて取得し、`_build_search_graph`が
探索用グラフ（`domain/routing.py: LazyRoadGraph`、`NodeSpatialIndex`）とbbox全体ぶんの
コスト配列を構築する。データ未整備（対象タイル未取込）ならNoneを返し、呼び出し元
（`RouteGenerator`）が候補0件として扱う。

`_build_search_graph`は、`StaticEdgeScoreMatrix`（風などリクエストごとに変わる動的軸の列は
NaN）へ動的軸（風、`domain/evaluation.py: evaluate_dynamic_axis_arrays`。材料id→evaluator
関数の登録制`DYNAMIC_MATERIAL_EVALUATORS`で軸名をハードコードしない汎用実装）と重み
ベクトルを適用し、`compose_costs_from_axis_matrix`・`compute_hard_filter_excluded`で
コスト配列（`_RoadGraphContext.cost_list`、`lazy_graph.edge_ids`と同じ行順）を1回だけ
合成する。並行Edge（同一Node間の複数Edge）は、`build_lazy_road_graph`がedge_idの昇順で
先頭を採用する決定的な規則で解消する（`LazyRoadGraph`がコストに依存せずタイル集合キーで
キャッシュされるための制約、次節参照）。同じ配列（`difficulty_array`・`axis_arrays`）は
`_build_segment_details`（区間表示）からも`full_edge_row`経由で参照され、探索コストと
表示の二重計算を避ける。

### 探索・索引構築のキャッシュ（`infrastructure/search_graph_cache.py`）

`LazyRoadGraph`（探索用グラフ）・`SearchGraphStatics`（一対全最短経路木
用のCSR構造＋Edge実距離配列）・`SearchGraphStatics`の転置版（後ろ向き木用、
[T551](../../tasks/T551.md)）・`NodeSpatialIndex`（routable Node空間索引）の4種は、
タイル集合キーのプロセス内LRUへキャッシュする。同じタイル集合への2回目以降の
リクエストはこれらの構築を丸ごと省略する。**上限件数は`LazyRoadGraph`/
`NodeSpatialIndex`が`DEFAULT_MAX_ENTRIES`（64）、`SearchGraphStatics`（順方向・転置版
とも）は`SEARCH_STATICS_MAX_ENTRIES`（16）と別立てにしてある**——1エントリがCSR構造
一式（`indptr`/`indices`/`entry_edge_index`）を保持し他の2種より重いため、同じ上限を
共有すると常駐メモリが不必要に大きくなりうる（改善計画T568、`/code-review`指摘）。

- **キー**: `LazyRoadGraph`・`SearchGraphStatics`（順方向・転置版とも）は
  `frozenset[(zoom,x,y)]`（bboxを覆うz12タイル集合）のみ。`NodeSpatialIndex`はこれに
  `hard_filters`・`max_average_grade_percent`（0次フィルタ、`RoadGraphEngine`の
  コンストラクタ引数）を加えたタプル。`GraphService.get_search_materials_for_bbox`が
  タイル集合を返すのは、graphが「bboxを覆う全z12タイルの材料キャッシュをそのまま
  結合したもの」の場合のみ——split鮮度が古くbbox限定で再構築した経路ではNoneが返り、
  呼び出し側はこのキャッシュを経由しない。
- `SearchGraphStatics`が持つCSR構造（`indptr`/`indices`とCSRエントリ順→Edge indexの
  並べ替え表）はタイル集合だけで決まる派生物のためキャッシュに含めるが、リクエストごとに
  変わるコスト配列は含めない——`select_loop_turnarounds`が一対全木を求めるたびに
  コスト配列をこの並べ替え表でCSRのdata順へ差し替えて`scipy.sparse.csr_matrix`を組む。
  `SearchGraphStatics`は一対全木を実際に使う`prepare`（`_get_or_build_search_statics`）
  だけが構築・キャッシュする——`preview_segment`は2点間の直接A*のみで一対全木を使わない
  ため、`LazyRoadGraph`はキャッシュしても`SearchGraphStatics`は構築しない
  ([T569](../../tasks/T569.md))。
- **転置版`SearchGraphStatics`**（`_get_or_build_reverse_search_statics`、
  `domain/routing.py: build_csr_structure(..., reverse=True)`）は、目的地からの
  後ろ向き木を使う`select_via_nodes`だけが構築・キャッシュする——周回生成・
  `preview_segment`・経由地を伴う目的地ルート（`trace_loop`）は使わない。`edge_length_m`
  は向きに依存しない配列のため順方向版と共有できる（別インスタンスとして持つ）が、`csr`
  はキー`v * node_count + u`（行・列を入れ替え）で組み直した別物。
- **無効化方針は`graph_material_cache`と同じ**（プロセス寿命でのみキャッシュ、軸定義変更は
  無関係、材料再取込の反映にはプロセス再起動が必要）。ただし例外として、タイル再split
  （`save_graph`のedge_id再割当）でキャッシュ済み`LazyRoadGraph.edge_ids`が新しい
  `graph.edges`に存在しなくなる不整合だけは、プロセス再起動を待たずリクエスト内で自己修復
  する——`RoadGraphEngine._build_search_graph`（`prepare`・`preview_segment`共通）が
  `_ensure_lazy_graph_consistent`で`domain/routing.py: find_missing_lazy_graph_edge_id`
  （CSR構築を伴わない軽量チェック）を毎回呼び、不整合を検知したら該当タイル集合の
  4キャッシュ（`LazyRoadGraph`・`SearchGraphStatics`・転置版`SearchGraphStatics`・
  `NodeSpatialIndex`）を破棄して`LazyRoadGraph`ごと`graph`から作り直す
  （`search_graph_cache.invalidate_tile_set`）。
- `_reverse_traced_edges`（逆回り候補、後述）は、キャッシュ済み`LazyRoadGraph.
  edge_index_by_node_pair`を経路上のEdgeだけに対する遅延引きとして使う。

### `select_loop_turnarounds`（折返し点選定）

起点からの一対全Dijkstra（`domain/routing.py: build_shortest_path_tree`、
scipy.sparse.csgraph、軸重み付きコスト、コスト上限で打ち切り）を1回求め、木に沿った
往路の実距離が`[max(0, (目標−許容)/2.0), (目標+許容)/2.3]`（下限が上限を超える狭い
許容では両方とも`(目標∓許容)/2.0`へ対称化）に入るNodeを「リング」として抽出する
（最短実距離ではなく軸コスト最適経路の実距離で定義する——重みを極端に振った設定ほど
往路が遠回りするため）。往路の距離加重平均difficulty（`overall_difficulty`と同じ
物差し、小数1桁へ丸めた値）の昇順、同点（丸め後のdifficultyが等しい）は「リング中心
（`目標/((2.0+2.3)/2)`、上下限の算術平均ではなく目標距離ベースで決める——許容が目標
以上で下限が0クランプされる場合に算術平均だと中心が0付近まで下がってしまうため）に
近い順」で並べたうえで、`_diversify_ties_by_bearing`が同点グループ内をさらに
方位（`geo.py: bearing_between_array`）の最遠点貪欲法で並べ替える——グループ内で
既に並べた候補との角距離の最小値が最大のものを優先し、グループの1件目（累積で
採用済みが無い時点）だけはリング中心近さ最小のまま。difficulty群自体の順序
（主キー）・同点でない候補間の順序はこの並べ替えでは変わらない
（[T554](../../tasks/T554.md)）。上位から
`domain/routing.py: select_diverse_by_overlap`で、既採用候補と往路の重複率が
`TURNAROUND_MAX_OVERLAP_RATIO`（0.6）を超えるもの・`MIN_TURNAROUND_SEPARATION_KM`
（1.5km）より近いものを飛ばして`pool_size`件採る（埋まらなければ
`TURNAROUND_RELAXED_OVERLAP_RATIO`＝0.85へ緩めてやり直す）。

### `trace_loop_from_turnaround`（復路探索）

往路は一対全木上の経路そのもの（`tree_path_edge_indices`で復元、A*での再探索はしない
——同じコスト配列でA*をかけ直しても同じ経路になるため）。復路探索の間だけ、往路Edge＋
同一Node対の逆方向Edgeのコストを共有`cost_list`上で`RETRACE_PENALTY_MULTIPLIER`
（8.0、infにはしない——復路が往路を戻る以外に道が無い区間[袋小路等]は通れる必要がある）
倍に**差し替え**、A*（復路の目的地は常に起点のため、ヒューリスティック配列は
リクエストで1回だけ計算し全候補で共有する）で探索した後、`try`/`finally`で元の値へ
復元する。この差し替えはawaitを挟まない同期区間で完結し、復路探索が同期・直列実行
（並列化すると共有`cost_list`の書き換えが競合するため両立しない）である前提の上で
安全。

### `select_via_nodes`（目的地ルートのvia-node方式代替経路、[T551](../../tasks/T551.md)）

経由地の無い目的地ルート（起点→目的地のみ）向け。周回の折返し点方式（1本の一対全木＋
候補ごとのretraceペナルティ付き復路A*）とは異なり、木2本だけで全候補が確定し候補ごとの
追加探索が発生しない:

1. 起点からの前向き木（`select_loop_turnarounds`と同じ`build_shortest_path_tree`）と、
   目的地からの後ろ向き木（転置CSR、`_get_or_build_reverse_search_statics`）を各1回求める。
2. 全Nodeについて経由路長`len_f+len_b`・合成コスト`cost_f+cost_b`をベクトル計算し、
   合成コスト最小のNode（＝経由地無しの従来の単一生成が返す経路、"最良路"）の長さの
   `ALTERNATIVE_MAX_STRETCH`（1.3）倍以内のNodeだけを候補にする。
3. 平均difficulty`(合成コスト/経由路長-1)/P`昇順に並べる。ただし最良路のNodeは常に
   先頭へ回す——伸び率の許す範囲でより平均difficultyの低い経路が他に存在すれば難易度順
   ではそちらが上位に来うるため、「最良路は必ず結果に含まれる」をランキングとは独立に
   保証する。
4. `domain/routing.py: select_diverse_by_overlap`で、前向き経路・後ろ向き経路が同じ
   物理区間を共有するNode（行って戻る形、`_loop_edge_lengths_by_physical_segment`で
   進行方向を無視した判定——単純なEdge index集合の比較だと同じ道の逆方向Edgeを
   見逃す）を除外しつつ、採用済み候補との重複率が`VIA_NODE_MAX_OVERLAP_RATIO`
   （`TURNAROUND_MAX_OVERLAP_RATIO`と同値の0.6、埋まらなければ0.85へ緩和）を超える
   ものを飛ばして`max_routes`件採る。

`trace_loop_from_turnaround`と違い、選ばれたNodeの経路（前向き＋後ろ向きの経路復元の
連結）がそのまま最終候補になる（`tree_path_edge_indices`/`tree_path_edge_indices_to_source`
で確定済み、候補ごとに失敗しうる探索が無い）ため、戻り値の`TracedLoop`一覧が
`RouteGenerator._generate_destination_routes`にとってそのまま`evaluate_loops`への入力になる。

### `trace_loop`（経由地・目的地指定ルート）

`select_loop_turnarounds`/`trace_loop_from_turnaround`は周回候補（フロンティア方式）
専用で、経由地・目的地指定ルート（`generate_via_waypoints`）は本メソッドが指定地点列を
順にA*で結ぶ（`bearing=None`固定、戻り値の`data`は経路上のedge_id列）。探索は
`asyncio.to_thread`による並列化をしない（rustworkxはEdgeごとにPythonコールバックへ
戻る構造のためGILを解放できず、複数スレッド並列は直列より遅いため）。

### `evaluate_loops`（実ジオメトリ取得・評価）

距離フィルタを通過した全候補ぶんのedge_idを1つにまとめ、`GraphService.
get_edges_with_geometry`を**1回のクエリ**で呼んで実ジオメトリを取得する（棄却済み候補への
DB問い合わせを避ける2段階分割を維持したまま、候補ごとには問い合わせない）。
取得後は候補ごとに`_build_best_candidate`を`asyncio.gather`で並行評価する（標高取得・
segments構築はEdge単位の軽量な計算のため並行化してよい。復路探索のような共有状態の
書き換えを伴わない）。`_build_segment_details`は、探索コスト算出時に`prepare`が既に
合成済みの軸別スコア配列・合成difficulty配列（`_RoadGraphContext.axis_arrays`/
`difficulty_array`）からそのまま値を読み、`RouteSegmentDetail`列へ
組み立てる（標高・風・路面等の表示専用フィールドはEdge単位の軽量な計算のまま）。

### `_build_best_candidate`（逆回りループ候補の代数的合成）

周回候補（waypoints指定でない場合）は、順方向の探索結果から逆方向候補を
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

bboxをz12タイルへ分解し、`graph_material_cache`（材料、プロセス内LRU、上限2,000タイル）と
`tile_score_matrix_cache`（`StaticEdgeScoreMatrix`、材料キャッシュとは別枠の
プロセス内LRU）をタイル単位で経由する。全タイルがキャッシュ済みならDBへの問い合わせも
Edge単位の軸別スコア算出も発生しない（`_get_or_build_tile_score_matrix`）。戻り値は
`tuple[SearchMaterials, StaticEdgeScoreMatrix, frozenset[tuple[int, int, int]] | None]`——
複数タイルにまたがる場合は`domain/evaluation.py: combine_static_edge_score_matrices`が
後勝ちセマンティクスで1つに結合する（`combined_edges.update(...)`と同じ結合順序）。
3要素目（タイル集合）は`_build_search_materials_from_tile_cache`経由の場合のみ
覆う全z12タイルの集合を持ち、`RoadGraphEngine`が`infrastructure/search_graph_cache.py`
（探索用グラフ・索引のタイル集合キーLRU）のキーとして使う。split鮮度が古い場合
（`_build_search_materials_uncached`）はNone——このgraphはタイル境界と一致しない不完全な
集合のため、タイルキャッシュ・search_graph_cacheのどちらへも書き込まない（応答後に
バックグラウンドで該当タイルを材料・スコア行列の両方とも温める、`_maybe_warm_tile_cache`→
`_warm_tile_cache_background`）。

**暗黙の前提**: `graph_material_cache`・`tile_score_matrix_cache`はプロセス内メモリLRUに
加え、`infrastructure/tile_persistent_cache.py`へディスク永続化する（`backend/data/
tile_persistent_cache/`、DEMタイルディスクキャッシュ`tile_cache.py`と同じ考え方）。
メモリmissでもディスクがあればDBへ問い合わせずに復元し、復元した値はメモリへも載せ直す。
ディスク側の無効化はバージョン文字列をファイルパスへ埋め込む方式
（`graph_material_cache.py: TILE_MATERIALS_CACHE_VERSION`・`tile_score_matrix_cache.py:
TILE_SCORE_MATRIX_CACHE_VERSION`、いずれも`region_service.py: ROAD_SURFACE_TILE_VERSION`と
同じ流儀）——PBF再取込・`presplit_road_graph.py`・関連precomputeバッチを実行したら手動で
上げる（各定数のコメント・`docs/batch-pipeline-dependencies.md`参照）。軸定義編集
（`refresh_axis_definitions`、アプリ起動時にも必ず1回呼ばれる）は
`tile_score_matrix_cache.sync_disk_cache_with_axis_revision(revision)`が
`axis_registry_meta.revision`の変化を見て判定する別経路（バージョン文字列は据え置いた
まま）——revisionがディスクへ最後に永続化した時点の記録と一致すればメモリだけ
クリアし、不一致（軸定義が実際に変わった）ならメモリ・ディスク両方を即座に削除する。
軸定義が変わっていないアプリ起動のたびにディスクキャッシュを丸ごと再構築しないための
区別で、`graph_material_cache`（`TILE_MATERIALS_CACHE_VERSION`のみで無効化、
軸編集では変化しない）とは無効化の粒度が異なる。

**キャッシュ表現**: `graph_material_cache`が保持する`SearchMaterials.materials`は、
タイルキャッシュ経由（`_get_or_build_tile_materials`）の場合`domain/attributes.py:
EdgeMaterialTable`（列指向、numpy配列＋リスト、`EdgeMaterialBundle`と1対1のビュー）を
持つ（`_build_search_materials_uncached`はタイルキャッシュへ書き込まれないため、
`dict[str, EdgeMaterialBundle]`のまま）。`EdgeMaterialTable.get(edge_id)`は必要になった
Edgeだけをその場で`EdgeMaterialBundle`へ組み立てる——探索フェーズが実際に材料を引くのは
経路上のEdge（数百本）だけで、bbox全体（数十万Edge）を毎回復元する構造ではない。複数
タイルを結合する`_build_search_materials_from_tile_cache`も、結合直後に全EdgeをEdge
MaterialBundleへ復元せず、`edge_id→タイルindex`の遅延ビュー（`_CombinedEdgeMaterials`）で
`.get(edge_id)`を該当タイルへ委譲する（同じ理由）。`LeanRoadGraph`（トポロジ側）も
`__reduce__`でNode/Edgeを列（tupleのリスト）へ分解してpickle化し、復元時に`LeanNode`/
`LeanEdge`をコンストラクタ呼び出しで作り直す。正準定義は引き続き`EdgeMaterialBundle`
1箇所（設計原則4）——`EdgeMaterialTable`は軸定義も材料カタログも知らない。詳細な設計判断は
[T546](../../tasks/T546.md)参照。

**並列度設定が効く範囲**: `config.py: tile_cache_load_max_concurrent`（既定
`min(4, os.cpu_count())`）が、`graph_service.py`の`_get_or_build_tile_materials`・
`_get_or_build_tile_score_matrix`が行うディスク永続化キャッシュ読み込み
（`asyncio.to_thread`経由）の同時実行数を縛る。Edgeの再構築自体は`LeanEdge`/
`EdgeMaterialBundle`のコンストラクタ呼び出しを伴うPythonループのためGILで直列化される
——この設定が効くのはファイルI/O・numpy配列の復元部分のみで、コア数に比例して線形に
速くなるのはグラフ側も完全列指向化する将来の別案（`LeanEdge`オブジェクト自体を持たない
設計）まで進めた場合に限る（[T546](../../tasks/T546.md)「比較した他案と採否」参照）。

### `get_edges_with_geometry`の同時実行ロック

`GraphService.__init__`が持つ`self._repository_lock`（`asyncio.Lock`）は、同一
`AsyncSession`への同時アクセス（未定義動作/例外を招く）を防ぐため、`asyncio.gather`配下から
repositoryへ到達しうる経路を直列化する。実際に同時実行されるのは
`_get_or_build_tile_materials`のキャッシュmiss時のDB問い合わせ（タイルごとにgatherで並行）
で、`get_edges_with_geometry`は`RoadGraphEngine.evaluate_loops`が距離フィルタ通過候補ぶんの
edge_idをまとめて1回・`preview_segment`が1回、いずれも逐次に呼ぶだけのため、同じロックを
取るのは将来の並列化に対する保険にすぎない（`GraphService`はリクエストごとに新規生成される
ため複数リクエスト間で共有されることも無い）。

## domain層

### `domain/routing.py`

- `LazyRoadGraph`/`build_lazy_road_graph`: 探索用グラフ。Node/Edgeのpayloadは整数index
  （`add_nodes_from(range(n))`・Edge payload=`edge_ids`の添字）で、A*のcost_fn/
  estimate_cost_fnは素の`list.__getitem__`を受け取る（探索中にPythonの関数フレームを
  作らない設計の核心）。`build_lazy_road_graph`に`edge_cost_by_id`（コスト辞書）を渡すと、
  並列Edge（同じnode対の重複辺）は**cost最小のEdgeを採用**する（コストが事前に判明して
  いるため）。省略時（コスト未確定の場面、主にテスト）はedge_idの昇順で先頭を採用する
  決定的な選択にフォールバックする。
- `shortest_path_node_ids_lazy`: `rustworkx.astar_shortest_path`を、探索が実際に訪れた
  Edge・Nodeに対してのみ都度呼ばれる`edge_cost_fn`/`estimate_cost_fn`（いずれも整数index
  引数）でラップする。Hard Constraintで除外するEdgeは`edge_cost_fn`が`math.inf`を返す
  ことで表現する（`LazyRoadGraph`自体はHard Constraintを知らない。この`math.inf`は
  探索前に`prepare`が合成したコスト配列へ既に焼き込み済み）。経路確定後、
  合計コストが有限かを検算してから返す（rustworkxが`inf`を「非常に高コストだが有効」
  として扱い、他に経路が無ければ採用してしまうことがあるため）。
- **`CsrGraphStructure`/`build_csr_structure`・`SearchGraphStatics`/
  `build_search_graph_statics`**: `LazyRoadGraph`と同じNode/Edge index
  空間のCSR（圧縮行格納）**構造のみ**（Edge重みは持たない。タイル集合だけで決まる
  純粋な派生物のため`LazyRoadGraph`と同じキーでキャッシュされる）。`SearchGraphStatics`は
  この構造とEdge実距離配列（m）を束ねる。両関数とも`reverse=True`（既定False）で
  転置CSR（キー`v * node_count + u`、行・列を入れ替え）を返す
  （[T551](../../tasks/T551.md)、目的地からの後ろ向き木用。`edge_length_m`は向きに
  依存しないため`reverse`の値に関わらず同じ配列になる）。`indptr`/`indices`/
  `entry_edge_index`はint32（改善計画T568。実データ規模のNode/Edge数はint32の値域に
  対して桁違いに小さい）。`from_index*node_count+to_index`の整列キー
  （`(pred, v)`のCSRエントリ位置検索用）はフィールドとして持たず、`indptr`/`indices`
  から`_reconstruct_entry_keys`が都度再構築する（タイル集合キーのプロセス内LRUが
  常駐させる1エントリぶんのメモリを削減する。キー自体の計算はint64——`node_count`の
  2乗がint32の値域を超えうるため）。
- **`ShortestPathTree`/`build_shortest_path_tree`**: 起点からの一対全
  Dijkstra（`scipy.sparse.csgraph.dijkstra`、前任者付き、`cost_limit`で打ち切り可能）。
  前任者木に沿った実距離（`length_m`）は、`(pred[v], v)`のCSRエントリ位置を
  `np.searchsorted`で一括検索した後、ポインタジャンプ（`acc[v] += acc[anc[v]]`を木の
  深さのlog2回繰り返す）でベクトル演算して積算する。rustworkxの
  `dijkstra_shortest_path_lengths`は前任者を返さないため一対全木にはscipyを使う。
  `CsrGraphStructure`が順方向・転置版のどちらでも同じロジックで木を組める（方向に
  依存する処理を持たない）ため、転置CSRを渡して`source_index=目的地`とするだけで
  「各Nodeから目的地までの最短経路コスト・実距離」（後ろ向き木）が得られる。
- **`tree_path_edge_indices`**: 一対全木（順方向）上の起点→targetの経路を
  `LazyRoadGraph`のEdge index列で返す（到達不能ならNone、起点自身なら空リスト）。
- **`tree_path_edge_indices_to_source`**: 後ろ向き木（転置CSR、`source_index`が目的地）
  で、targetから目的地までの経路を実グラフの有向Edge順（target→…→目的地）のEdge
  index列で返す（[T551](../../tasks/T551.md)）。転置CSR上の`predecessor[X]=P`は実
  グラフの`X→P`という辺を表すため、`tree_path_edge_indices`（`(parent, current)`順で
  Edge検索し最後に反転）とはEdge検索の引数順が逆（`(current, parent)`）で、経路は
  既に`target→目的地`の順に積み上がるため反転は不要。
- **`overlap_ratio`/`select_diverse_by_overlap`**: 2つのEdge index集合の
  距離加重重複率、およびランク順の候補列から重複率・近接度（`is_compatible`）で貪欲に
  多様な集合を選ぶ汎用関数（周回の折返し点選定・目的地ルートのvia-node選定の両方に使う）。
  採用済み集合はEdgeごとのuint64ビットマスク1本（bit `i`＝「採用済み`i`件目がこのEdgeを
  含む」、常駐メモリはEdge数×8B）で持つ——`max_count`（実際の呼び出し元の上限は
  `TURNAROUND_POOL_MAX`=40・`MAX_ROUTES`=15）は64を超えられず、超える呼び出しは
  `ValueError`になる。
- `RoadGraphEngine.is_loop_too_similar`（`LoopRoutingEngine`契約、`_loop_edge_lengths_by_
  physical_segment`）: 距離フィルタ合格後の候補が、既に採用済みの候補と周回全体
  （`TracedLoop.data`、往路＋復路のedge_id列）で`LOOP_MAX_OVERLAP_RATIO`（0.7、往路のみ
  比較する`TURNAROUND_MAX_OVERLAP_RATIO`＝0.6より緩め）を超えて重複するか判定する。
  edge_idを`{from_node_id, to_node_id}`のfrozensetへ正規化し進行方向を無視して比較する
  ため、「同じ周回の逆回り」・「往路は違うが復路が同じ裏道へ収束する」周回のどちらも
  同じ判定で弾ける。
- `NodeSpatialIndex`/`build_node_spatial_index`/`find_nearest_node_indexed`:
  グリッドバケットによる最近傍ノード探索。
- `compute_routable_node_ids`（`domain/evaluation.py`）: 最近傍ノード探索は「0次
  ハードフィルタを通過したEdgeが最低1本残るノード」だけに制限する（制限しないと孤立
  ノード——幹線道路にしか面していない駅等——が最近傍として選ばれ、経路探索が失敗しうる）。
  lazy評価ではEdgeコストを事前計算しないため、Hard Constraintだけを軽量に評価する
  専用関数として`domain/evaluation.py`に置く（`domain/routing.py`側には持たない）。
  入力は`EdgeMaterialBundle`辞書ではなく、`StaticEdgeScoreMatrix`の生配列
  （`edge_ids`＋`compute_hard_filter_excluded`が返す`excluded`配列、`_build_search_graph`が
  コスト配列を`inf`にするのに使うのと同じ配列）——タイル材料キャッシュの復元コストと
  完全に独立している。
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

`geo.py`は球面三角法の地理計算（`haversine_distance_km`・`haversine_distance_km_array`・
`bearing_between`・`compass_label`）を持つ。`LatLon`（`Protocol`）・
`LatLonPoint`（`NamedTuple`）は`Coordinates`（Pydantic、API境界の入力検証用）を経由
せずに緯度経度を扱うための軽量な構造的型で、`build_road_graph`・最近傍ノード探索のような
ホットパスがバリデーションコストを避けるために使う。「起点から方位θへ距離d進んだ点」を
求める`destination_point`は本番コードから参照されないため、テスト専用ヘルパー
`tests/geo_fixtures.py`に置き（`test_road_graph_engine.py`の合成グラフ・`test_geo.py`の
座標生成が使う）、`geo.py`には持たない。

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
動的取得するための経路。正規化式（`_MATERIAL_VALUE_COLUMN_EXPR`）は`infrastructure/
osm_way_tag_sql.py`の共有断片を`_ROAD_SURFACE_TILE_MVT_SQL`・`material_coverage.py`
（[evaluation-scoring.md](evaluation-scoring.md)）と共通で参照する。詳細は
[axis-studio.md](axis-studio.md)参照。

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
- **`GraphService`の`_repository_lock`が守るのは`asyncio.gather`配下からrepositoryへ
  到達する経路だけ**（`_get_or_build_tile_materials`のDB問い合わせと、保険としての
  `get_edges_with_geometry`）——他のメソッドは常に逐次実行段階でしか呼ばれないため
  ロック不要という前提に立っている。`evaluate_loops`の`asyncio.gather`
  （`_build_best_candidate`の並行評価）内からrepositoryへ到達する呼び出しを新たに
  追加する場合は、同じロックを取らない限りこの前提が崩れることに注意。
- **`graph_material_cache`・`tile_score_matrix_cache`はプロセス内メモリLRU＋
  `tile_persistent_cache.py`によるディスク永続化の2段構成**——ディスクの無効化は
  `TILE_MATERIALS_CACHE_VERSION`/`TILE_SCORE_MATRIX_CACHE_VERSION`のバージョン文字列を
  手動で上げる方式（`region_service.py: ROAD_SURFACE_TILE_VERSION`と同じ流儀）。上げ忘れると
  デプロイでプロセスが再起動しても対象タイルがディスク経由で古い値のまま返り続ける
  （`docs/batch-pipeline-dependencies.md`「3. ランタイム側の読み取り元」参照）。
- **`tile_score_matrix_cache`（タイル単位の静的Edge×公開軸スコア行列）は
  `graph_material_cache`とは別枠**——軸スタジオでの軸定義編集
  （`AxisRegistryAdminService`→`refresh_axis_definitions`）はこちらだけを対象に無効化を
  判定し、材料キャッシュ（DBアクセスを伴う取得）は常に温存する。編集直後の最初の
  リクエストがDBへ再問い合わせせずに済む設計上の分離。`sync_disk_cache_with_axis_
  revision`は`axis_registry_meta.revision`が前回ディスクへ永続化した時点と一致するかで
  判定する——`refresh_axis_definitions`はアプリ起動時にも必ず1回呼ばれるため、軸定義が
  実際には変わっていない起動のたびにディスクキャッシュを丸ごと再構築しないための区別
  （不一致時はメモリ・ディスク両方を即座に削除、バージョン文字列は据え置いたまま。
  軸編集はデプロイを伴わない実行時操作のため）。
- **`search_graph_cache`（探索用グラフ・索引）はタイル集合キー**——
  `graph_material_cache`/`tile_score_matrix_cache`（いずれもタイル単位のキー）とは
  粒度が異なる。`GraphService.get_search_materials_for_bbox`が「タイルキャッシュを
  そのまま結合したgraph」を返した場合のみ有効なタイル集合が得られ、split鮮度が
  古いbbox限定の再構築経路ではこのキャッシュ自体を経由しない。
