# ルート生成エンジン・経路探索（backend）

## 責務

出発地点（＋任意で経由地・目的地）から、周回または経由地ルートの候補を複数生成し、
距離・難易度でスコアリングして返す。実際の経路計算・軸評価はroad_graphエンジン
（自前Road Graph + 辺基準グラフのlazy探索）が担う。Road Graph自体（ノード・Edge・交差点分割・
空間索引）の構築・永続化・キャッシュもこのモジュールが担う。

**対象ファイル**

| レイヤー | ファイル |
|---|---|
| domain | `routing.py`・`graph.py`・`route.py`・`geo.py`・`errors.py`・`cycling_speed.py`（自転車の走行モデル。平地・無風の巡航速度からホイール出力を逆算し、勾配・向かい風・転がり抵抗から区間ごとの速度を走行方程式で解く。速度の逆算は`v`の3次方程式になるため二分法で、numpyでベクトル化してある。候補の所要時間と基準線の探索コストがここから出る） |
| services | `route_generator.py`（戦略層）・`road_graph_engine.py`・`graph_service.py` |
| infrastructure | `road_graph_models.py`・`road_graph_repository.py`（4リポジトリ）・`graph_material_cache.py`・`tile_score_matrix_cache.py`・`search_graph_cache.py`・`tile_persistent_cache.py`・`cache_identity.py`（キャッシュ鍵の組み立て方の正本。手で書くリビジョンと、焼き込みSQL・pickleする列構成から導く署名を合成する。タイル配信側の世代も同じ関数を使う）・`derived_data_meta.py`（派生データの世代。バッチが中身を書き直すたびに進む単調カウンタで、デプロイを伴わない変化を表せる唯一の経路）・`cache_generation.py`（DBの世代とディスクへ書いた時点の記録を突き合わせる判断。軸定義と派生データが同じ実装を使う）・`osm_way_tag_sql.py`（`osm_raw_ways`のOSMタグ分類SQL断片の単一の情報源、[evaluation-scoring.md](evaluation-scoring.md)の`material_coverage.py`と共有） |
| api | `routes.py` |
| batch | `precompute_road_node_degrees.py`・`presplit_road_graph.py` |

road_graphエンジンは自前Road Graph（DB由来のノード/Edge）で経路計算する。探索の状態は
**有向区間**で、交差点でのターンに費用を付けられる（下記「一対全木の状態」節）。一対全木も
2点間探索もnumbaでJITしたDijkstra/A*（`build_turn_expanded_tree`・
`turn_expanded_shortest_path`）で、**出発からの経過時間をラベルとして持ち回れる**。
**コストの単位は秒**で、中身は「体感の所要時間」＝
`区間の所要時間 × (1 + penalty_strength × difficulty/100)`。所要時間は走行モデル
（`domain/cycling_speed.py`、勾配・風から区間ごとの速度を解く）＋停止の待ち、ターンの待ちは
遷移ごとに秒で足す。利用者の好み（軸の重み）をすべて0にすると素の所要時間になり、それが
`select_fastest_route`の返す基準線と同じ物差しになる。

Edgeコストは「タイル単位の静的Edge×公開軸スコア行列＋リクエスト時ベクトル計算」方式で
算出する——探索が実際に訪れたEdgeに対してPythonのコスト計算コールバックを都度呼ぶのでは
なく、`prepare`/`preview_segment`が対象bbox全体ぶんの
コスト配列を1回だけnumpyで合成し、探索へは合成済みの配列をそのまま渡す（探索中にPythonの
関数フレームを作らない）。
標高（勾配）は事前計算済み`elevation_attributes`をキー参照するだけで組み込み済み
（探索中にGSI API呼び出しは発生しない）。風は**到達時刻ごと**に効く——レグを時刻ビンへ
刻み、ビンごとのコスト配列を探索前に合成しておいて、探索が到達時刻をラベルとして運ぶ
（下記「レグ内の時刻ビン」）。

### レグ内の時刻ビン

レグは、見込み所要時間（`compose(duration_hours=...)`）ぶんを`TIME_BIN_HOURS`ごとのビンへ
分けて合成する。到達時刻をラベルとして持ち回れる探索はビンを引き、**経過時間の推定ではなく
実際の経過時間**で風を評価する。ビンの幅は風の予報の刻みより細かくしても元データの解像度を
超えないことから決まり、本数の上限（`MAX_TIME_BINS`）はビン1本ごとにbbox全体のコスト合成が
1回走ることとのトレードオフ。

表示と、時刻ラベルを持てない探索（目的地から遡る木）はレグの中間地点が入るビンを代表として
読む。**目的地モードの後ろ向き木だけは時刻ビンを使えない**ため、前向き木が出した「起点から
その区間へ実際に到達する時間」を通過時刻として渡す——直線距離からの推定より実態に近く、
候補は伸び率の上限内に制限されるためずれもその範囲に収まる。周回モードは往路が前向き木、
復路が前向きA*で、どちらも実際の経過時間を持ち回る。

風の時別系列があれば、**風に依存する軸の重みが0でも**時刻で引き直す。風は「避けたい度合い」
である前に走行モデルの入力（向かい風で実際に遅くなる）のため。

### レグ別コスト配列（`_LegCostComposer`・`LegCostArrays`）

探索アルゴリズムは時刻を知らない（配列への`list.__getitem__`しか行わない）ため、
「いつ通過するか」は探索前に配列を合成する側で決める。`_build_search_graph`は静的スコア
行列・重み・0次フィルタ・`lazy_graph`行順の対応表をリクエストにつき1回だけ用意した
`_LegCostComposer`を作り、`compose(label, anchor, offset_hours, direction)`がレグごとに
風の列だけを引き直して合成する（`domain/wind.py: estimate_passage_hours`、
`direction=+1`は基準点から離れるレグ、`-1`は基準点へ向かうレグで`offset_hours`が
到着予定時刻）。合成結果`LegCostArrays`は`cost_lazy`（`lazy_graph.edge_ids`順）と表示用の
`difficulty_array`/`axis_arrays`/`weight_sums`/`material_arrays`（動的材料id→
`full_edge_row`順配列の辞書、`evaluate_dynamic_material_arrays`が返す全材料のうち値がある
ものだけ）を持ち、`_RoadGraphContext.legs`に添字順で並ぶ。`compose`は
`DynamicAxisRequestContext`へ風の入力と走行速度（`speed_kmh`を`kmh_to_ms`でm/sへ変換）を
渡し、風の材料（`wind_drag_ratio`）はこのcontextから求まる:

| 用途 | 添字0 | 添字1〜 |
|---|---|---|
| 周回 | 往路（基準点=起点、`offset=0`、`+1`） | 復路（基準点=起点、`offset=目標距離÷速度`、`-1`）——`select_loop_turnarounds`が合成 |
| 目的地ルート（via-node） | 前向き木（同上） | 後ろ向き木（基準点=目的地、`offset=直線距離×迂回率÷速度`、`-1`）——`select_via_nodes`が合成 |
| 経由地ルート（`trace_loop`） | レグ0 | レグk（基準点=レグ起点、`offset=累積実距離÷速度`、`+1`）を逐次合成 |
| `preview_segment` | 往路のみ | — |

`TracedLoop.leg_of_edge`が経路上の各Edgeのレグ添字を運び、`_build_segment_details`は
そのレグの配列から値を読む（探索と表示の一致、[設計原則](../../design-principles.md)10）。
`RouteSegmentDetail.material_values`/`RouteCandidate.material_values`（重み>0の公開軸が
参照する材料id→値、`AXIS_DEFINITIONS`の`materials`プロパティから導出、
`_active_material_ids`が集合を決める）は、動的材料（風等）は`material_arrays`から
（`_material_value_at`）、静的材料（`gradient_percent`）はEdgeごとに計算済みの値を
そのまま読む。`_active_material_ids`はリクエストの`lens_axis_id`（地図のレンズが表示を
要求している軸）が符号付き材料の軸（`map_value_kind`が`signed_material`）を指す場合、
その軸の材料も重みに関わらず含める（地図の色分けが重み0の軸でも成立するため）。
逆回り候補はレグ割当ても反転する（先に走る側が往路配列、`_reverse_leg_assignment`）。レグ番号は走行順に振られるため、Edge列の反転と同時に番号自体も`max_leg - leg`へ振り直す。起点の時別風予報
（`WeatherService.get_wind_forecast_series`、`get_conditions`と同じ応答・キャッシュ）が
無い場合は、出発時点のスナップショットで合成した1本を全レグで共有する（追加コスト
ゼロ）。**重みが0でも時刻ビンは畳まない**——走行モデル（向かい風は速度そのものを落とす）が
時刻で変わるため、重み0を理由に時刻固定へ落とすと所要時間が狂う。ただし`lens_axis_id`が風に依存する公開軸なら、
重み0でも区間表示のためレグごとに合成する（探索コストには影響しない、
`_LegCostComposer`の`lens_axis_id`）。
仮定巡航速度は`RouteGenerateRequest.assumed_speed_kmh`（既定`ASSUMED_SPEED_KMH`）で
リクエストごとに変えられ、通過予定時刻と風の材料`wind_drag_ratio`（走行速度依存）の
両方に効く。迂回率（道なり距離÷直線距離）は定数ではなく実測値を使う。直線距離を走行時間へ直す係数
として使うもので、`prepare`が同じ探索範囲（タイル集合）で前回学習した値
（無ければ`ROUTE_DETOUR_RATIO`）を合成器へ渡す。往路木を求めるたびに実測の中央値
（周回はリングNode、目的地ルートは起点から1km以上の到達Node）を測って
`search_graph_cache.set_detour_ratio`へ学習値として保存し（`_median_detour_ratio`・
`_learn_detour_ratio`）、目的地ルートの後ろ向きレグはその場で測った値で到着予定時刻を置く。
**周回の復路レグは迂回率を読まない**——総所要時間は目標距離÷仮定速度で決まる（距離
フィルタが目標±許容を強制する）。運用時は`_build_search_graph`のINFOサマリ
（`wind_time_varying`・`speed_kmh`・`detour_ratio=値(learned|default)`）、
`compose_leg_costs`ログ（`leg`・`mode`・`bins`・`compose_ms`）、
`select_turnarounds`/`select_via_nodes`の`detour_ratio_median`で確認できる。

`RouteGenerateRequest.waypoints`/`destination`（経由地・目的地指定）にも対応する
（`api/routers/routes.py: generate_routes`）。

## 戦略層（`route_generator.py: RouteGenerator`）

`LoopRoutingEngine`という契約（`route_generator.py`のProtocol定義が正本。
`prepare`・`trace_loop`・`evaluate_loops`等）を挟むことで、`RouteGenerator`自体は
探索エンジンの内部実装を知らない設計になっている（将来別方式のエンジンを差し込める余地を持たせるための抽象化）。
現在の実装は`RoadGraphEngine`のみ。

候補の形は公開軸の重み配分で決まる（フロンティア方式）:
起点からの一対全最短経路木（軸重み付きコスト）で目標距離の半分付近に到達する折返し点を
選び、往路と別の復路を探索して周回にする。距離は目標±`distance_tolerance_km`の厳格
フィルタで、スコアとは混ぜない（1つの数字へ合成すると、比較不能な2つを重み配分が勝手に
決めてしまう）。

**折返し点の並びはパレート層の順にする**（`domain/routing.py: pareto_layer_index`）。
「リング中心からのずれ」「往路difficulty」の2指標で非優越ソートし、第1層（他のどの候補にも
両方で負けていない候補）から順にプールへ採る。劣解＝「目標距離により近く、かつより易しい
候補が他にあるので誰も選ぶ理由がない」を意味する。difficultyが距離加重「平均」であるため、
これが無いと遠回りして難所を避けた候補が常に上位を占め、「目標距離ちょうどだが難所を
通る」候補が一覧に現れない。

第1層だけでは候補が数件にしかならない（2次元のパレートフロントは点の数が増えても
ほとんど大きくならない）ため、プールが埋まるまで層を重ねる。第1指標が往路実距離そのもの
ではなくリング中心からのずれなのは、周回では距離が「短いほど良い」ではなく「目標に近い
ほど良い」ため——目標より短すぎる往路（起点のすぐ近くで折り返す周回）も長すぎる往路も
対称に扱う。目的地ルートは目標距離を持たないため、そちらは経路長そのものを第1指標にする
（`select_via_nodes`）。

**暗黙の前提**: 丸めた結果2指標とも同値になった候補は互いを支配せず、全員が同じ層に入る。
起点から全方位が等距離・同難易度という対称な地形でこれが層へばらけると、`tie_groups`
（同点グループ）が壊れて`prefer`（方位の最遠点貪欲法）が働かなくなり、選ばれる折返し点の
方位が偏る。同点グループの区切りもdifficultyだけでなく層番号を見る。

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
  engine.evaluate_loops(context, traced, start_time)  # start_time=リクエストのstart_time（省略時はdatetime.now(JST)）、prepare(now=start_time)にも渡す
        │  フィルタ通過候補だけに実ジオメトリ取得・標高・風・路面等の評価を行う
        ▼
  RouteGenerator._evaluate_and_aggregate() の集約段
        │  区間segmentsから距離加重で候補単位の集約値（overall_difficulty・軸別の
        │  difficulty／寄与度／生値・材料値等）を付ける。候補を返す経路はすべてこの
        │  1メソッドを通るため、集約を増やしてもここだけに書けば全経路へ効く
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
- 候補は折返し点候補のランク順に逐次処理する（復路探索が共有`cost_lazy`を一時的に
  書き換える同期処理のため`asyncio.gather`による並列化の余地は無い）。距離フィルタ合格が
  `max_routes`件に達した時点で処理を打ち切る。
- 候補0件になった理由は`RouteGenerator.last_no_candidates_reason`に人間可読な文字列で
  残り、`RouteGenerateResponse.no_candidates_reason`としてクライアントへ返る。

### `generate_spliced_route`（区間の乗り換え）

クライアントが候補の`edge_ids`から区間を差し替えて組み立てた経路を、**探索をやり直さず**
1件だけ評価して返す（[T621](../../tasks/T621.md)）。`POST /api/routes/generate`へ
`spliced_edge_ids`を添えると、折返し点選定・via-node選定を通らずこの経路へ入る
（`destination`必須。合成の対象は目的地ルートだけで、周回は起点へ戻る制約があるため）。

**別エンドポイントにしていない**のは、合成も生成と同じコスト曲線だから——経路は確定済み
でも`prepare`は通る（評価は`_RoadGraphContext`のコスト配列から読む。design-principles.md
構造仕様10）。`prepare`は温まっていても1秒前後、タイル材料が冷たいと数十秒かかるため、
202＋ポーリングのジョブ機構がそのまま要る（数値は[T621](../../tasks/T621.md)）。

送られたEdge id列が**実在し・順につながり・起点から始まる**ことは
`engine.build_traced_from_edge_ids`が確かめ、成立しなければ`RoutingError`で落とす
（グラフを知るのはエンジンのため戦略層には置けない）。レグは合成経路自身の距離の半分で
切る——via-nodeが無く前向き木・後ろ向き木の境目が存在しないため。

### `generate_via_waypoints`（経由地・目的地指定）

`generate_loops`の折返し点選定・距離フィルタとは独立した経路生成。
`destination`省略時は起点に戻る周回（常に1件）。

`destination`指定時は、経由地の有無で分岐する:

- **経由地が無い（起点→目的地のみ）**: `_generate_destination_routes`が
  `engine.select_via_nodes`（via-node方式、後述）で`max_routes`件まで互いに異なる
  代替経路を生成する。`overall_difficulty`昇順（`generate_loops`と同じ規約）で
  `id="route-destination-00"`形式へ振り直し、`direction_label="目的地ルート"`を
  全件に付ける。
  併せて`engine.select_fastest_route`（所要時間だけで選ぶ、後述）を1本必ず含め、
  `RouteCandidate.is_fastest=True`を付けて**難易度順の外へ出し先頭へ固定**
  する。軸設定に沿った候補が基準線からどれだけ余計にかかるかを読むための基準であり、
  難易度で沈むと基準として使えないため。軸最良の候補と同じ経路になった場合は候補を
  増やさずその1本へ印を付ける。件数は`max_routes`を超えず、切るのは末尾（最も難易度の
  高い候補）。**`max_routes`が1のときは先頭固定しない**——基準線は比べる相手があって
  初めて基準であり、1本だけ返すときに固定すると返る唯一の候補が常に時間最短になって
  軸の重みが結果に現れない。
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
エンジンが方位から付けた表示用ラベルのまま）。経由地の無い目的地ルートも同じ規約で
idを`route-destination-00..`へ振り直すが、
「目標距離」という概念自体が無いため同点タイブレークは持たない（`select_via_nodes`の
`select_diverse_by_overlap`が既に決定的な順序で候補を返す）。

## RoadGraphEngine（`road_graph_engine.py`）

自前Road Graphを`GraphService`経由で取得し、`domain/routing.py`の辺基準グラフ探索で
探索する。Edgeコストは`prepare`が対象bbox全体ぶんを**1回だけnumpyで合成**し、探索へは
合成済みのnumpy配列をそのまま渡す
——探索中にPythonのコールバックを作らない（本ファイル冒頭「road_graphエンジン」節参照。
グラフ構造自体は必要になった時点でEdgeを実体化するlazy構築のままで、「lazy」が指すのは
グラフ構築であってコスト計算ではない）。周回候補は
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
edge_attribute_counts・way_tags・elevation_attributes・designated_edge_ids・
way_landcoverのtrees_percent/built_percent[T624]、Edge単位で
`EdgeMaterialBundle`へ統合済み）＋`StaticEdgeScoreMatrix`（タイル単位で
キャッシュ済みの「Edge×公開軸」静的スコア行列）をまとめて取得し、`_build_search_graph`が
探索用グラフ（`domain/routing.py: LazyRoadGraph`、`NodeSpatialIndex`）とbbox全体ぶんの
コスト配列を構築する。データ未整備（対象タイル未取込）ならNoneを返し、呼び出し元
（`RouteGenerator`）が候補0件として扱う。

`_build_search_graph`は、`StaticEdgeScoreMatrix`（風などリクエストごとに変わる動的軸の列は
NaN）へ動的軸（風、`domain/dynamic_materials.py: evaluate_dynamic_axis_arrays`。材料id→evaluator
関数の登録制`DYNAMIC_MATERIAL_EVALUATORS`で軸名をハードコードしない汎用実装）と重み
ベクトルを適用し、`compose_costs_from_axis_matrix`・`compute_hard_filter_excluded`で
コスト配列を1回だけ合成する。合成結果はレグ（往路/復路）ごとに`LegCostArrays`
（`cost_lazy`[`lazy_graph.edge_ids`と同じ行順]・`difficulty_array`・`axis_arrays`）へ
まとまり、`_RoadGraphContext.legs`が保持する（下記「レグ別コスト配列」節）。並行Edge
（同一Node間の複数Edge）は、`build_lazy_road_graph`がedge_idの昇順で先頭を採用する
決定的な規則で解消する（`LazyRoadGraph`がコストに依存せずタイル集合キーでキャッシュ
されるための制約、次節参照）。同じ`LegCostArrays`は`_build_segment_details`（区間表示）
からも`full_edge_row`経由で参照され、探索コストと表示の二重計算を避ける。

**走行モデルが読む入力は軸の構成に依存しない**。勾配は静的スコア行列が常に持つ生配列
（0次フィルタの勾配しきい値と同じ列）から、停止の回数は
`domain/traffic.py: stop_count_material_ids`が宣言する材料から読む——「内訳として画面へ
見せる材料」だけを運ぶ既定に任せると、軸を非公開にした瞬間に所要時間の中身が静かに変わる。

### 探索の状態（`domain/routing.py: TurnExpandedStructure`）

一対全最短経路木も2点間探索も、状態を交差点Nodeではなく**有向区間**に取る。交差点で直進したか右左折
したかは「入る区間×出る区間」の対で決まり、Nodeを状態にすると表せないため。ターンの費用は
進入・退出の方位差から秒で決め（`TurnCostSpec`）、そのままコストへ足す（探索のコストも
秒のため換算は要らない）。
加えて、**交差点に集まる道の最大階級が進入した区間より上位なら**、横断（直進）・右左折に
それぞれ費用を足す（`domain/traffic.py: highway_rank`で比べる。信号の有無は見ない——信号の
ある交差点の待ちは停止密度の軸が数えており、二重になるため）。探索側は階級の意味を知らず、
比較結果だけを使う。

グラフは辺基準へ物理的に展開せず、遷移は`SearchGraphStatics`のCSRから導く。目的地から
遡る木は同じ遷移を転置した配列（`TurnExpandedStructure.reverse_transitions`、最初に
要求されたときだけ組む）を使う——ターンの待ちは元の進行方向のまま運ぶ。

一対全木も2点間探索もnumbaでJITした実装で、優先度キューをnumpy配列のバイナリヒープとして
持つ。**到達時刻をラベルとして持ち回るため、ライブラリ（scipy等）は使えない**——コストが
辺の静的な属性であることを前提にしているため、時刻で変わるコストを表せない。アルゴリズム
自体は教科書どおりのDijkstra/A*で、独自のものは作らない。コスト配列は1次元（時刻に
依存しない）か`(時刻ビン, 状態)`の2次元で渡し、2次元のときは素の所要時間とビンの幅も
一緒に渡す。**状態ごとに保つラベルはコスト最小の1本だけ**（1ラベル法）で、「コストは高いが
早く着く」経路を捨てる近似になる。`preview_segment`もこの探索を通るため、2点間だけの経路
でも遷移を導くCSR構造（`SearchGraphStatics`）を構築する。

Nodeごとのコストは、そのNodeへ入る区間の最小を採る（木を作るときに畳む）。
**起点Nodeだけは「起点へ戻ってくるコスト」になる**——状態の空間に「まだ走っていない」が
無いため。前向き木と後ろ向き木をNodeで繋ぐときは`combine_forward_backward_at_nodes`を
通す。Nodeごとのコストを単に足すと、そのNodeで曲がる費用が抜ける。

### 探索・索引構築のキャッシュ（`infrastructure/search_graph_cache.py`）

`LazyRoadGraph`（探索用グラフ）・`SearchGraphStatics`（一対全最短経路木
用のCSR構造＋Edge実距離配列）・`NodeSpatialIndex`（routable Node空間索引）と、
探索範囲ごとに学習した迂回率（float 1個、「レグ別コスト配列」節参照）は、
タイル集合キーのプロセス内LRUへキャッシュする。同じタイル集合への2回目以降の
リクエストはこれらの構築を丸ごと省略する。**上限件数は`LazyRoadGraph`/
`NodeSpatialIndex`が`DEFAULT_MAX_ENTRIES`（64）、`SearchGraphStatics`は
`SEARCH_STATICS_MAX_ENTRIES`（16）と別立てにしてある**——1エントリがCSR構造
一式（`indptr`/`indices`/`entry_edge_index`）を保持し他の2種より重いため、同じ上限を
共有すると常駐メモリが不必要に大きくなりうる。

- **キー**: `LazyRoadGraph`・`SearchGraphStatics`は
  `frozenset[(zoom,x,y)]`（bboxを覆うz12タイル集合）のみ。`NodeSpatialIndex`はこれに
  `hard_filters`・`max_average_grade_percent`（0次フィルタ、`RoadGraphEngine`の
  コンストラクタ引数）を加えたタプル。`GraphService.get_search_materials_for_bbox`が
  タイル集合を返すのは、graphが「bboxを覆う全z12タイルの材料キャッシュをそのまま
  結合したもの」の場合のみ——split鮮度が古くbbox限定で再構築した経路ではNoneが返り、
  呼び出し側はこのキャッシュを経由しない。
- `SearchGraphStatics`が持つCSR構造（`indptr`/`indices`とCSRエントリ順→Edge indexの
  並べ替え表）はタイル集合だけで決まる派生物のためキャッシュに含めるが、リクエストごとに
  変わるコスト配列は含めない——`select_loop_turnarounds`が一対全木を求めるたびに
  コスト配列は探索へnumpy配列のまま渡す。
  `SearchGraphStatics`は一対全木を実際に使う`prepare`（`_get_or_build_search_statics`）
  だけが構築・キャッシュする——`preview_segment`は2点間の直接A*のみで一対全木を使わない
  ため、`LazyRoadGraph`はキャッシュしても`SearchGraphStatics`は構築しない。
- **ターン展開構造**（`TurnExpandedStructure`）は`TurnStructureKey`（タイル集合と
  `TurnCostSpec`の組）でキャッシュする。遷移とターンの費用はこの2つだけで決まるため、
  同じタイル集合・同じターン費用なら作り直す必要がない。
- **無効化方針は`graph_material_cache`と同じ**（プロセス寿命でのみキャッシュ、軸定義変更は
  無関係、材料再取込の反映にはプロセス再起動が必要）。ただし例外として、タイル再split
  （`save_graph`のedge_id再割当）でキャッシュ済み`LazyRoadGraph.edge_ids`が新しい
  `graph.edges`に存在しなくなる不整合だけは、プロセス再起動を待たずリクエスト内で自己修復
  する——`RoadGraphEngine._build_search_graph`（`prepare`・`preview_segment`共通）が
  `_ensure_lazy_graph_consistent`で`domain/routing.py: find_missing_lazy_graph_edge_id`
  （CSR構築を伴わない軽量チェック）を毎回呼び、不整合を検知したら該当タイル集合の
  キャッシュ（`LazyRoadGraph`・`SearchGraphStatics`・`NodeSpatialIndex`）を破棄して
  `LazyRoadGraph`ごと`graph`から作り直す
  （`search_graph_cache.invalidate_tile_set`）。
- `_reverse_traced_edges`（逆回り候補、後述）は、キャッシュ済み`LazyRoadGraph.
  edge_index_by_node_pair`を経路上のEdgeだけに対する遅延引きとして使う。

### `select_loop_turnarounds`（折返し点選定）

起点からの一対全Dijkstra（`domain/routing.py: build_turn_expanded_tree`、
軸重み付きコスト、コスト上限で打ち切り）を1回求め、木に沿った
往路の実距離が`[max(0, (目標−許容)/2.0), (目標+許容)/2.3]`（下限が上限を超える狭い
許容では両方とも`(目標∓許容)/2.0`へ対称化）に入るNodeを「リング」として抽出する
（最短実距離ではなく軸コスト最適経路の実距離で定義する——重みを極端に振った設定ほど
往路が遠回りするため）。往路の距離加重平均difficulty（`overall_difficulty`と同じ
物差し、小数1桁へ丸めた値）の昇順、同点（丸め後のdifficultyが等しい）は「リング中心
（`目標/((2.0+2.3)/2)`、上下限の算術平均ではなく目標距離ベースで決める——許容が目標
以上で下限が0クランプされる場合に算術平均だと中心が0付近まで下がってしまうため）に
近い順」で並べる。同点の候補は`domain/routing.py: select_diverse_by_overlap`へ
グループ（`tie_groups`）として渡し、グループ内の試行順は`_order_by_bearing_spread`
（`prefer`）が「採用済み候補との方位（`geo.py: bearing_between_array`）の角距離の
最小値が最大」の順に決め、1件採用するたびに残り候補へ対して決め直す（最遠点貪欲法。
方位は生成機構ではなく同点タイブレーク専用で、比較対象は採用済み候補[最大`pool_size`件]
だけのため計算量は走査件数×採用件数に留まる）。採用済みが無い時点ではリング中心近さ順。
difficulty群自体の順序（主キー）・同点でない候補間の順序はこの並べ替えでは変わらない。
`select_diverse_by_overlap`は上位から、既採用候補と往路の重複率が
`TURNAROUND_MAX_OVERLAP_RATIO`（0.6）を超えるもの・`MIN_TURNAROUND_SEPARATION_KM`
（1.5km）より近いものを飛ばして`pool_size`件採る（埋まらなければ
`TURNAROUND_RELAXED_OVERLAP_RATIO`＝0.85へ緩めてやり直す）。

### `trace_loop_from_turnaround`（復路探索）

往路は一対全木上の経路そのもの（`turn_expanded_path_edge_indices`で復元、A*での再探索はしない
——同じコスト配列でA*をかけ直しても同じ経路になるため）。復路探索の間だけ、往路Edge＋
同一Node対の逆方向Edgeのコストを共有`cost_lazy`上で`RETRACE_PENALTY_MULTIPLIER`
（8.0、infにはしない——復路が往路を戻る以外に道が無い区間[袋小路等]は通れる必要がある）
倍に**差し替え**、A*（復路の目的地は常に起点のため、ヒューリスティック配列は
リクエストで1回だけ計算し全候補で共有する）で探索した後、`try`/`finally`で元の値へ
復元する。この差し替えはawaitを挟まない同期区間で完結し、復路探索が同期・直列実行
（並列化すると共有`cost_lazy`の書き換えが競合するため両立しない）である前提の上で
安全。

### `select_via_nodes`（目的地ルートのvia-node方式代替経路）

経由地の無い目的地ルート（起点→目的地のみ）向け。周回の折返し点方式（1本の一対全木＋
候補ごとのretraceペナルティ付き復路A*）とは異なり、木2本だけで全候補が確定し候補ごとの
追加探索が発生しない:

1. 起点からの前向き木（`select_loop_turnarounds`と同じ`build_turn_expanded_tree`）を求める。
   目的地に一番近いNode（`find_nearest_node_indexed`、次数1以上のみが候補[T256]）が
   この前向き木で到達不能な場合（歩道橋・私有地内通路等、メインの道路網から孤立した
   小さな塊へスナップされたケース）、`find_nearest_node_indexed`へ「前向き木が届くNode」
   だけを候補にする`predicate`を渡して再スナップする（実際の座標は
   `_RoadGraphContext.destination_correction`に残り
   `RouteGenerator.last_destination_correction`→`GenerationConditions.
   corrected_destination`経由でレスポンスへエコーされる）。再スナップも失敗した場合は
   候補0件として扱う。**このとき壊れているのが目的地側とは限らない**——
   `find_nearest_node_indexed`は索引全体を走査するため、候補が1つも見つからないのは
   「前向き木がどのNodeへも届かなかった」ときにも起きる（起点が孤立している・合成コストが
   全Edgeで非有限、等）。到達Node数を見てどちら側かを判定し、警告と
   `_RoadGraphContext.no_candidates_side`（`RouteGenerator`が利用者向けの文面を選ぶ）で
   区別する。
2. （補正後の）目的地からの後ろ向き木（遷移の向きを反転した辺基準の木）を求める。
3. 全Nodeについて経由路長と合成コストを`combine_forward_backward_at_nodes`で求め
   （そのNodeで曲がる費用を含む）、
   合成コスト最小のNode（＝経由地無しの従来の単一生成が返す経路、"最良路"）の長さの
   `ALTERNATIVE_MAX_STRETCH`（1.3）倍以内のNodeだけを候補にする。
4. 平均difficulty`(合成コスト/経由路長-1)/P`昇順に並べる。ただし最良路のNodeは常に
   先頭へ回す——伸び率の許す範囲でより平均difficultyの低い経路が他に存在すれば難易度順
   ではそちらが上位に来うるため、「最良路は必ず結果に含まれる」をランキングとは独立に
   保証する。並べた後に`MAX_VIA_NODE_CANDIDATES_EXAMINED`件で打ち切る（周回の折返し点
   選定と同じ規則。**並べる前に切ると**Node index順の任意の集合を残すことになり、良い
   候補が理由なく落ちる）。打ち切ったときはWARNINGを出す。
5. `domain/routing.py: select_diverse_by_overlap`で、前向き経路・後ろ向き経路が同じ
   物理区間を共有するNode（行って戻る形、`_loop_edge_lengths_by_physical_segment`で
   進行方向を無視した判定——単純なEdge index集合の比較だと同じ道の逆方向Edgeを
   見逃す）を除外しつつ、採用済み候補との重複率が`VIA_NODE_MAX_OVERLAP_RATIO`
   （`TURNAROUND_MAX_OVERLAP_RATIO`と同値の0.6、埋まらなければ0.85へ緩和）を超える
   ものを飛ばして`max_routes`件採る。

`trace_loop_from_turnaround`と違い、選ばれたNodeの経路（前向き＋後ろ向きの経路復元の
連結）がそのまま最終候補になる（`turn_expanded_path_from_state`/
`turn_expanded_path_from_state_to_source`で確定済み、候補ごとに失敗しうる探索が無い）ため、戻り値の`TracedLoop`一覧が
`RouteGenerator._generate_destination_routes`にとってそのまま`evaluate_loops`への入力になる。

### `select_fastest_route`（好みの重みを0にしたときの基準線）

コスト配列に区間ごとの素の所要時間（`LegCostArrays.travel_seconds_lazy`＝走行モデルの
走行時間＋停止の待ち、主観的割増を掛ける前の下地そのもの）を渡すため、**時間最短**の経路が
1本得られる。利用者の好み（軸の重み）をすべて0にしたときの経路であり、
候補が基準線に対して何を犠牲に何を得たかを読むための物差しになる。コストが秒のため
A*のヒューリスティックも秒の下界にする（直線距離÷出せる最大速度）。

**軸の重みは使わないが、0次フィルタ（`no_bicycle`・`motorway`・`trunk`・
`max_average_grade_percent`）は使う**——これらは好みではなく通行可否・走行可否の表明で、
所要時間を優先する経路でも越えてよいものではない。除外Edgeの所要時間を`inf`にすることで
表現する（軸コスト経路で`cost_lazy`が`inf`になっているのと同じ意味）。

`select_via_nodes`の後に呼ぶ前提で、目的地の再スナップ結果（`destination_correction`）を
引き継ぐ。レグは経路の所要時間が半分になる位置で割る——他の候補と同じく往路レグ・
復路レグへ概ね半分ずつ割れ、レグごとに時刻の異なる風の評価が候補間で揃う。

### `trace_loop`（経由地・目的地指定ルート）

`select_loop_turnarounds`/`trace_loop_from_turnaround`は周回候補（フロンティア方式）
専用で、経由地・目的地指定ルート（`generate_via_waypoints`）は本メソッドが指定地点列を
順にA*で結ぶ（`bearing=None`固定、戻り値の`data`は経路上のedge_id列）。

### `evaluate_loops`（実ジオメトリ取得・評価）

距離フィルタを通過した全候補ぶんのedge_idを1つにまとめ、`GraphService.
get_edges_with_geometry`を**1回のクエリ**で呼んで実ジオメトリを取得する（棄却済み候補への
DB問い合わせを避ける2段階分割を維持したまま、候補ごとには問い合わせない）。
取得後は候補ごとに`_build_best_candidate`を`asyncio.gather`で並行評価する（標高取得・
segments構築はEdge単位の軽量な計算のため並行化してよい。復路探索のような共有状態の
書き換えを伴わない）。`_build_segment_details`は、探索コスト算出時に`prepare`が既に
合成済みの`LegCostArrays`（`axis_arrays`・`difficulty_array`）からそのまま値を読み、
`RouteSegmentDetail`列へ組み立てる（標高・風・路面等の表示専用フィールドはEdge単位の
軽量な計算のまま）。

**戻り値は入力の`traced`と同じ件数・同じ順**（位置で対応づける契約）。戦略層は
`TracedLoop.data`の中身を知らないため、どの候補がどの`TracedLoop`由来かを位置以外で
突き合わせられない（基準線への印付けがこれに依存する）。件数のずれは
`RouteGenerator._evaluate_and_aggregate`が`RoutingError`で落とす——ずれても候補が消えるわけでは
なく、印・ラベルだけが静かに入れ替わるため結果からは気づけない。

### `_build_best_candidate`（逆回りループ候補の代数的合成）

周回候補（waypoints指定でない場合）は、順方向の探索結果から逆方向候補を
**追加のDB/API呼び出し無しに代数的に導出**する: 標高の獲得/喪失を入れ替え、勾配の符号を
反転し、既にhydrate済みのgeometryを再利用する（`_reverse_traced_edges`/
`_reverse_elevation_attribute(s)`）。両方向の`distance_weighted_difficulty`を比較し、
小さい方を採用する（`_pick_better_candidate`）。`TracedLoop.bearing is None`
（waypoints指定ルート）ではこの逆回り合成をスキップする——ユーザーが指定した訪問順序を
尊重する必要があるため。

### 夜間軸の動的重み付け

**出発地点・出発時刻の1点**（`prepare`の時点、`is_night(wind_and_night_origin, now)`）で
昼夜を判定し、その結果をルート全体へ一様に適用する——市民薄明の外（夜間）なら夜間軸の
重みをそのまま、日中なら0倍にした`RoutePreference`のコピーを探索コストへ渡す
（`RoutePreference.with_time_scope`。`domain/axis_definitions.py: time_scoped_weights`が
`AxisDefinition.time_scope="night_only"`を持つ軸を汎用的に判定するため、軸idの
ハードコードは無い）。風がEdgeごとの通過予定時刻で引く（下記「レグ別コスト配列」）のとは
異なる粒度である点に注意（末尾「暗黙の前提のまとめ」参照）。

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
ディスク側の無効化はバージョン文字列をキーへ含める方式
（`graph_material_cache.py: TILE_MATERIALS_CACHE_VERSION`・`tile_score_matrix_cache.py:
TILE_SCORE_MATRIX_CACHE_VERSION`）。この文字列は`infrastructure/cache_identity.py`が
「手で書くリビジョン＋形の署名」として組み立てる——pickleする`dataclass`の列構成が署名に
入るため、列を足す・消す・並べ替えると鍵が自動で変わり、古いキャッシュを復元して最後の列が
欠けたまま実体化する事故が起きない。形は同じまま読み先のデータを作り直したとき（PBF再取込・
`presplit_road_graph.py`・関連precomputeバッチ、`docs/batch-pipeline-dependencies.md`参照）は
バージョン文字列ではなくDBの世代が表す——バッチの入口が`derived_data_meta.revision`を進め、
`services/derived_data_revision_service.py`がTTL付きで読み直して、ディスクへ書いた時点の
記録と違えば材料とスコア行列の両方を捨てる。バッチはデプロイを伴わないため、コード内の
定数では表せない。スコア行列側の鍵は材料側の世代も材料に含める
複合で、材料世代を上げれば機械的に追従する——スコア行列は材料からの派生物で、材料の
`edge_id`集合が変われば必ず無効になるため（片方だけ上がった状態だと、`graph`には在るが
`score_matrix.edge_ids`には無い`edge_id`が生じ、`full_edge_row`引きがbbox単位で
KeyErrorになる）。`cache_identity.SCORE_MATRIX_REVISION`を単独で上げるのは、同じ材料・
同じ列から違う値を作るようになったときに限る。軸定義編集
（`refresh_axis_definitions`、アプリ起動時にも必ず1回呼ばれる）は
`tile_score_matrix_cache.sync_disk_cache_with_axis_revision(revision)`が
`axis_registry_meta.revision`の変化を見て判定する別経路（バージョン文字列は据え置いた
まま）——revisionがディスクへ最後に永続化した時点の記録と一致すればメモリだけ
クリアし、不一致（軸定義が実際に変わった）ならメモリ・ディスク両方を即座に削除する。
軸定義が変わっていないアプリ起動のたびにディスクキャッシュを丸ごと再構築しないための
区別で、`graph_material_cache`（軸編集では変化せず、派生データの世代の変化だけで捨てる）
とは無効化の粒度が異なる。

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
1箇所（design-principles.md構造仕様4）——`EdgeMaterialTable`は軸定義も材料カタログも知らない。

**並列度設定が効く範囲**: `config.py: tile_cache_load_max_concurrent`（既定
`min(4, os.cpu_count())`）が、`graph_service.py`の`_get_or_build_tile_materials`・
`_get_or_build_tile_score_matrix`が行うディスク永続化キャッシュ読み込み
（`asyncio.to_thread`経由）の同時実行数を縛る。Edgeの再構築自体は`LeanEdge`/
`EdgeMaterialBundle`のコンストラクタ呼び出しを伴うPythonループのためGILで直列化される
——この設定が効くのはファイルI/O・numpy配列の復元部分のみで、コア数に比例して線形に
速くなるのはグラフ側も完全列指向化する将来の別案（`LeanEdge`オブジェクト自体を持たない
設計）まで進めた場合に限る。

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

- `LazyRoadGraph`/`build_lazy_road_graph`: 探索用グラフ。Node/Edgeの識別は整数index
  （Edge index=`edge_ids`の添字）で、探索はコストをnumpy配列のまま受け取る（探索中に
  Pythonのコールバックを作らない設計の核心）。並行Edge（同じnode対の重複辺）はedge_idの
  昇順で先頭を採用する決定的な選択で解消する（タイル集合キーでキャッシュするための制約、
  「探索・索引構築のキャッシュ」節参照）。
- **`CsrGraphStructure`/`build_csr_structure`・`SearchGraphStatics`/
  `build_search_graph_statics`**: `LazyRoadGraph`と同じNode/Edge index
  空間のCSR（圧縮行格納）**構造のみ**（Edge重みは持たない。タイル集合だけで決まる
  純粋な派生物のため`LazyRoadGraph`と同じキーでキャッシュされる）。`SearchGraphStatics`は
  この構造とEdge実距離配列（m）を束ねる。両関数とも`reverse=True`（既定False）で
  転置CSR（キー`v * node_count + u`、行・列を入れ替え）を返す（`edge_length_m`は向きに
  依存しないため`reverse`の値に関わらず同じ配列になる）。`indptr`/`indices`/
  `entry_edge_index`はint32（実データ規模のNode/Edge数はint32の値域に
  対して桁違いに小さい）。辺基準グラフの遷移は`build_turn_expanded_structure`が
  この3配列から導くため、Node対からCSRエントリ位置を引き直す整列キーは持たない。
- **`TurnCostSpec`/`TurnExpandedStructure`/`build_turn_expanded_structure`**:
  状態＝有向区間・辺＝ターンの遷移構造（「探索の状態」節参照）。`CsrGraphStructure`と
  同じくEdge重みは持たず、遷移とターンの秒だけを持つ。グラフを物理的に展開せず遷移を
  `CsrGraphStructure`から導くため、`LazyRoadGraph`と同じキーでキャッシュできる。
  `edge_bearings`（区間の方位）・`turn_seconds_for`（方位差→秒）が入力になる。
- **`TurnExpandedTree`/`build_turn_expanded_tree`**: 起点からの一対全Dijkstra
  （numba、前任者付き、`cost_limit`で打ち切り可能）。実距離と素の所要時間は緩和のたびに
  そのまま積むため、前任者を遡り直す積算が要らない。状態ごとの値に加え、Nodeごとの
  値（そのNodeへ入る区間の最小）も持つ。
  `reverse=True`で遷移の向きだけを反転する（ターンの費用は元の進行方向のまま）。
  **逆向きの木は時刻ビンを使えない**——目的地から遡るため各状態の到達時刻が決まらない。
  複数ビンを渡すと`ValueError`で弾く（黙って通すと、到達時刻の代わりに「残り時間」で
  ビンが引かれ、例外もNaNも出ないまま時刻が反転した条件で評価した経路が返る）。
- **`turn_expanded_path_from_state`/`turn_expanded_path_from_state_to_source`/
  `turn_expanded_path_edge_indices`**: 木上の経路をEdge index列で復元する（順に
  「始点→その状態」「その状態→目的地（後ろ向き木）」「始点→そのNode」）。
- **`combine_forward_backward_at_nodes`/`NodeJunction`**: 前向き木と後ろ向き木を
  Nodeで繋ぐ。Nodeごとのコストを単に足すとそのNodeで曲がる費用が抜けるため、
  繋ぎ目の区間の対ごとにターンの費用を足して最小を採る。
- **`turn_expanded_shortest_path`/`_turn_expanded_astar`**: 2点間探索。numbaでJITし、
  優先度キューをnumpy配列のバイナリヒープとして自前で持つ（`heapq`は使えない）。
- **`overlap_ratio`/`select_diverse_by_overlap`**: 2つのEdge index集合の
  距離加重重複率、およびランク順の候補列から重複率・近接度（`is_compatible`）で貪欲に
  多様な集合を選ぶ汎用関数（周回の折返し点選定・目的地ルートのvia-node選定の両方に使う）。
  候補列の代わりに同点グループ列（`tie_groups`）と、グループ内の試行順を採用済みリストに
  応じて返す`prefer`を渡せる（1件採用するたびに残り候補へ呼び直す。周回の折返し点選定が
  方位タイブレークに使う）。
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
- `compute_routable_node_ids`（`domain/hard_filters.py`）: 最近傍ノード探索は「0次
  ハードフィルタを通過したEdgeが最低1本残るノード」だけに制限する（制限しないと孤立
  ノード——幹線道路にしか面していない駅等——が最近傍として選ばれ、経路探索が失敗しうる）。
  lazy評価ではEdgeコストを事前計算しないため、Hard Constraintだけを軽量に評価する
  専用関数として0次フィルタのモジュール（`domain/hard_filters.py`）に置く
  （`domain/routing.py`側には持たない）。
  入力は`EdgeMaterialBundle`辞書ではなく、`StaticEdgeScoreMatrix`の生配列
  （`edge_ids`＋`compute_hard_filter_excluded`が返す`excluded`配列、`_build_search_graph`が
  コスト配列を`inf`にするのに使うのと同じ配列）——タイル材料キャッシュの復元コストと
  完全に独立している。

### `domain/graph.py`

- `Node`/`DirectedEdge`/`RoadGraph`（Pydantic）と、`NodeLike`/`EdgeLike`/
  `RoadGraphLike`（Protocol）で構造的型付けする`LeanNode`/`LeanEdge`/`LeanRoadGraph`
  （dataclass、探索専用の高速版。Pydanticのバリデーション・内部簿記コストを避けるため
  探索フェーズに限りdataclassを使う）が並存する。

### `domain/route.py`

- `Coordinates`・`RouteSegment`・`RouteSegmentDetail`（**material_valuesに入る
  符号付き材料（`gradient_percent`等）は符号付きが正準契約**——絶対値ではない。
  frontend`routeStyleModes.ts`がこの契約に依存する）・`RouteCandidate`。
- `aggregate_segments_into_bins`（500m区間ビニング）・`merge_axis_difficulties`・
  `merge_axis_contributions`・`merge_axis_raw_values`・`merge_material_values`・
  `merge_material_category_shares`・`_merge_segment_bin`。**`_merge_segment_bin`は表示用の
  区間を組み直す場所のため、`RouteSegmentDetail`へ辞書フィールドを足したらここへも集約を
  書き足す**（足し忘れは型でも例外でも現れず、APIからは「そのフィールドだけ空」に見える）。
  引き継がない辞書フィールドは`BIN_DROPPED_DICT_FIELDS`が理由つきで宣言し、それ以外が
  すべて引き継がれていることを`tests/test_route.py`が**値の型を問わずに**検査する
  （`dict[str, float]`のように値型で母集団を絞ると、`dict[str, str]`のフィールドが
  検査から静かに外れる）。
- **`RouteCandidate.edge_point_offsets`は、その経路のEdgeが`geometry.coordinates`の
  どこで切り替わるか**を`edge_ids`より1件多く持つ。隣接Edgeの境界点は重複させずに連結する
  （`_concat_edge_geometries`）ため、**座標列だけからはEdgeの境目を復元できない**。
  Edge単位で決めた区間を地図へ帯として描くのに要る。座標列と境界の位置は同じ関数が
  同時に作る——別々に組み立てるとずれても型でも例外でも現れず、帯だけが1点ずれる。
- **`RouteCandidate.edge_ids`は畳む前の経路そのもの**（`_build_candidate`が
  `edges_in_path`から起点順に載せる）。`segments`は約500m単位へ畳まれてEdgeと1対1に
  ならないため、経路の同一性を判定できるのはこちらだけ。フロントは候補どうしの共通部分を
  集合演算で求めて別の道を通る区間を出し、backendはステートレスのため乗り換え後の経路も
  このidの列で受け取って評価し直す（[T621](../../tasks/T621.md)）。
- **categorical材料の延長割合はビニングより前に畳む**。ビンの代表値を1つ選ぶ形だと割合が
  500m単位へ量子化されるため、`road_graph_engine`が`aggregate_segments_into_bins`の前に
  `merge_material_category_shares`を呼び、結果を`RouteCandidate`へ載せる。
  `route_generator`の後段はこの値に触らない（触ると、区間側が空になっている以上
  必ず`{}`で上書きされる）。

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

### キャッシュ（ルート生成はRedisを使わない）

ルート生成の経路で使うキャッシュはプロセス内メモリとディスクだけで、Redisを経由しない。

| 層 | 対象 | 実装 |
|---|---|---|
| プロセス内（件数上限LRU） | 探索用グラフ・タイル材料・静的スコア行列 | `search_graph_cache.py`・`graph_material_cache.py`・`tile_score_matrix_cache.py` |
| ディスク | タイル材料・静的スコア行列（プロセス再起動をまたぐ） | `tile_persistent_cache.py`（`diskcache`の包み。容量上限とLRU退避をライブラリが持つ） |
| ディスク | 標高DEMタイル | `tile_cache.py` |

タイルの取込完了判定（`road_graph_tiles`、1,000行規模）とsplit鮮度判定
（`is_split_up_to_date`の空間クエリ）は、いずれも数ミリ秒で終わるためキャッシュせず毎回
PostGISへ問い合わせる。エッジの実ジオメトリ（`get_edges_with_geometry`）も同様に毎回読む。
判断をキャッシュしない理由は[docs/caching.md](../../caching.md)参照——別プロセスのバッチが
生データを書き換えるため、判断を保持すると危険側（「splitは最新」）で古い値を返しうる。

## API（`api/routers/routes.py`）

| エンドポイント | 内容 |
|---|---|
| `POST /api/routes/preview` | 2点間の単純なルート取得（`get_preview_builder`経由。`RoadGraphEngine.preview_segment`を使う。`RouteGenerator`の周回戦略は使わない） |
| `POST /api/routes/generate` | 202を即座に返す非同期ジョブ投稿。`asyncio.create_task`でジョブ本体（`_run_generate_job`）を起動し、タスク参照を`_running_generate_tasks`が保持する（`BackgroundTasks`だとレスポンス送出の失敗でジョブが起動せず、投稿時点で取得済みのセマフォが解放されない） |
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

- **夜間の判定は出発時点1点で決まる**: 出発地点・出発時刻の昼夜判定をルート全体へ
  一様適用する。風は上記「レグ別コスト配列」のとおりEdgeごとの通過予定時刻で引くが、
  風の空間変化（bbox内で風が違う）は扱わず起点1地点の時別予報を全Edgeへ使う。
- **`GraphService`の`_repository_lock`が守るのは`asyncio.gather`配下からrepositoryへ
  到達する経路だけ**（`_get_or_build_tile_materials`のDB問い合わせと、保険としての
  `get_edges_with_geometry`）——他のメソッドは常に逐次実行段階でしか呼ばれないため
  ロック不要という前提に立っている。`evaluate_loops`の`asyncio.gather`
  （`_build_best_candidate`の並行評価）内からrepositoryへ到達する呼び出しを新たに
  追加する場合は、同じロックを取らない限りこの前提が崩れることに注意。
- **`graph_material_cache`・`tile_score_matrix_cache`はプロセス内メモリLRU＋
  `tile_persistent_cache.py`によるディスク永続化の2段構成**——ディスクの無効化は
  `TILE_MATERIALS_CACHE_VERSION`/`TILE_SCORE_MATRIX_CACHE_VERSION`のバージョン文字列で行う
  （`infrastructure/cache_identity.py`が列構成の署名から導出する）。形が変わらないまま
  読み先のデータを作り直した場合はこの文字列が動かないため、DBの`derived_data_meta.revision`
  （バッチの入口が進める）とディスクの記録を突き合わせて捨てる別経路が要る
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
