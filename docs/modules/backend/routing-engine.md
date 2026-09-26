# ルート生成エンジン・経路探索（backend）

## 責務

出発地点（＋任意で経由地・目的地）から、周回または経由地ルートの候補を複数生成し、
距離・難易度でスコアリングして返す。実際の経路計算・軸評価はroad_graphエンジン
（自前Road Graph + 辺基準グラフのlazy探索）が担う。取込範囲全体の道路網をPostGISから
番号の配列として作って常駐させ、生成のたびに範囲を切り出して探索用のグラフ・空間索引へ組む
ところまでがこのモジュールの範囲で、交差点で切った区間そのものは取込・派生バッチが範囲全体ぶん
先に作る（web側は作らない）。

**対象ファイル**

| レイヤー | ファイル |
|---|---|
| domain | `road_network.py`（取込範囲全体の道路網を、有向の区間とノードの番号で引ける列の配列として持つ型。行の並び・分類の材料を語彙への番号で持つことはそのdocstringが持つ）・`routing.py`・`graph.py`・`route.py`・`geo.py`・`errors.py`・`region.py`（矩形（`BoundingBox`）と地点を覆う矩形の組み立て、XYZタイルとの相互変換（緯度経度・Web Mercatorのメートル・同じ式のSQL）。タイル配信・取込・派生バッチもこの変換を共有する）・`cycling_speed.py`（自転車の走行モデル。平地・無風の巡航速度からホイール出力を逆算し、勾配・向かい風・転がり抵抗から区間ごとの速度を走行方程式で解く。速度の逆算は`v`の3次方程式になるため二分法で、numpyでベクトル化してある。候補の所要時間と基準線の探索コストがここから出る）・`tuning.py`（ルーティング評価が読む固定値の宣言。走ってみて決める値［較正値］は既定ごとここが持ち、エンジンが読む値・管理画面が並べる項目・変更が効くために何をやり直す必要があるかをそこから導く。較正値ではない固定値は載せず、使う側のモジュールが持つ）・`loop_routing.py`（周回・目的地ルートの探索結果を運ぶ型。探索の実装と候補を並べる戦略のどちらにも属さない） |
| services | `route_generator.py`（戦略層）・`road_graph_engine.py`・`graph_service.py` |
| infrastructure | `road_graph_repository.py`（道路網・材料の読み出し専用）・`road_network_store.py`（道路網全体の配列をDBから作り、ディスクへ置き、読む）・`detour_ratio_cache.py`（探索範囲ごとに学習した迂回率）・`cache_identity.py`（キャッシュ鍵の組み立て方の正本。手で書くリビジョンと、焼き込みSQL・列構成から導く署名を合成する。道路網の置き場の形の署名とタイル配信側の世代も同じ関数を使う）・`container_memory.py`（このプロセスのコンテナのメモリ上限。読み込む量の上限を導く）・`derived_data_meta.py`（派生データの世代。バッチが中身を書き直すたびに進む単調カウンタで、デプロイを伴わない変化を表せる唯一の経路） |
| api | `routes.py` |

探索が読む`road_edges`と材料のテーブル（ORMの宣言）・それを作るバッチは
[静的道路属性・タイル配信](static-road-attributes.md)の対象ファイル表が持つ。

road_graphエンジンは自前Road Graph（DB由来のノード/Edge）で経路計算する。探索の状態は
**有向区間**で、交差点でのターンに費用を付けられる（下記「一対全木の状態」節）。一対全木も
2点間探索もnumbaでJITしたDijkstra/A*（`build_turn_expanded_tree`・
`turn_expanded_shortest_path`）で、**出発からの経過時間をラベルとして持ち回れる**。
**コストの単位は秒**で、中身は「体感の所要時間」＝
`区間の所要時間 × (1 + penalty_strength × difficulty/100)`。所要時間は走行モデル
（`domain/cycling_speed.py`、勾配・風から区間ごとの速度を解く）＋停止の待ち、ターンの待ちは
遷移ごとに秒で足す。利用者の好み（軸の重み）をすべて0にすると素の所要時間になり、それが
`select_fastest_route`の返す基準線と同じ物差しになる。走行モデルの空気抵抗は相対風速の
大きさ×進行方向の相対風速に比例し、横風は相対風速の大きさにだけ効く——同じ強さの向かい風ほどは
遅くならない。

Edgeコストは「探索範囲の静的Edge×公開軸スコア行列＋リクエスト時ベクトル計算」方式で
算出する——探索が実際に訪れたEdgeに対してPythonのコスト計算コールバックを都度呼ぶのでは
なく、`prepare`/`preview_segment`が対象bbox全体ぶんの
コスト配列を1回だけnumpyで合成し、探索へは合成済みの配列をそのまま渡す（探索中にPythonの
関数フレームを作らない）。
標高（勾配）は派生済みの`edge_materials`を材料として読むだけで組み込み済み
（探索中にGSI API呼び出しは発生しない）。風は**到達時刻ごと**に効く——レグを時刻ビンへ
刻み、ビンごとのコスト配列を探索前に合成しておいて、探索が到達時刻をラベルとして運ぶ
（下記「レグ内の時刻ビン」）。

### レグ内の時刻ビン

レグは、見込み所要時間（`compose(duration_hours=...)`）ぶんを`TIME_BIN_HOURS`ごとのビンへ
分けて合成する。到達時刻をラベルとして持ち回れる探索はビンを引き、**経過時間の推定ではなく
実際の経過時間**で風を評価する。ビンの幅は風の予報の刻みより細かくしても元データの解像度を
超えないことから決まり、本数の上限（`MAX_TIME_BINS`）はビン1本ごとにbbox全体のコスト合成が
1回走ることとのトレードオフ。

**同じ時刻のビンは1回だけ合成する**。ビンを刻むレグの各ビンは、同じ開始時刻のビン1本のレグが合成済みなら
それを使う——周回・目的地ルートの往路は、`prepare`が見込み時間なしで合成した1本と同じ時刻から始まる。
逆向き（ビンを刻んだレグの途中のビンを、あとのビン1本のレグへ回す）は使い回さない。代表以外のビンは
コスト・所要時間の行だけを残して表示用の配列を捨てるため、使い回すにはビンごとに全部を持ち続けることになる。

時刻ラベルを持てない探索（目的地から遡る木）はレグの中間地点が入るビンを代表として読む。
**表示（区間の値・到達予想・所要）は代表ビンを読まない**——経路を探索と同じ規則でたどり
（`_route_passages`: レグの最初の区間はビン0、次の区間は前の区間を抜けた時点［曲がる待ちを足す前］の
経過時間のビン、区間の秒はそのビンの`travel_bins_lazy`）、区間ごとに探索が使ったビンを決める。
到達予想と所要はこのたどりの時計（走行モデル＋停止の待ち＋曲がる待ち）で出すので、最後の区間の
到達予想＋その区間の秒が所要に一致する。ビンが2本以上あるレグの区間は、経路上の行だけをそのビンの
時刻で合成し直して読む（`_LegCostComposer.values_at_rows`、合成と同じ`_evaluate`を行で切って使う）
——全ビンの表示用配列をリクエストの間持ち続けないため。区間の評価に使った風（予報の時刻・風向風速・
ビンや予報の範囲の先で延ばして使ったか）は`RouteSegmentDetail.wind`に載る（`winds_at`）。
ビンの本数の上限（レグごとに`MAX_TIME_BINS`×`TIME_BIN_HOURS`時間）は、区間の詳細の説明が
数字で示せるよう生成物`route-generate-config.json`の`wind_forecast_hours_per_leg`へ書き出す。
**目的地モードの後ろ向き木だけは時刻ビンを使えない**ため、前向き木が出した「起点から
その区間へ実際に到達する時間」を通過時刻として渡す——直線距離からの推定より実態に近く、
候補は伸び率の上限内に制限されるためずれもその範囲に収まる。周回モードは往路が前向き木、
復路が前向きA*で、どちらも実際の経過時間を持ち回る。

風の時別系列があれば、**風に依存する軸の重みが0でも**時刻で引き直す。風は「避けたい度合い」
である前に走行モデルの入力（向かい風で実際に遅くなる）のため。

### レグ別コスト配列（`_LegCostComposer`・`LegCostArrays`）

探索アルゴリズムは時刻を知らない（配列への`list.__getitem__`しか行わない）ため、
「いつ通過するか」は探索前に配列を合成する側で決める。`_build_search_graph`は静的スコア
行列・重み・0次フィルタ・`lazy_graph`行順の対応表をリクエストにつき1回だけ用意した
`_LegCostComposer`を作り、`compose(label, anchor, offset_hours, direction)`がレグごとに合成する
（`direction=+1`は基準点から離れるレグ、`-1`は基準点へ向かうレグで`offset_hours`が到着予定時刻）。
ビンを刻むレグは各ビンの開始時刻を全区間の通過時刻として合成し、時刻ラベルを持てない目的地から遡る木だけは
区間ごとの通過時刻（`passage_hours`。前向き木の実際の到達時間、届かない区間だけ
`domain/wind.py: estimate_passage_hours`の直線距離からの推定）で1本に合成する。

**時刻ビンごとに行うのは、その時刻の風に依る計算だけ**。風に依らない計算——走行モデルの出力と速度に
依らない抵抗（`domain/cycling_speed.py: SegmentSpeedModel`）・停止の待ち——はリクエストに1回だけ求めて
使い回す。時刻で変わる公開軸（風に依存する軸）の重みがすべて0なら、合成の難易度と割増の倍率も時刻に依らないので
1回だけ求め、ビンのコストは所要時間にその倍率を掛けるだけになる（重みが0の軸は合成に何も足さない）。重みが
あれば、時刻で変わらない軸の重み付き和を1回だけ求め、時刻で変わる軸だけをビンごとに足す。1ビンの中でも、
予報の引き当てと風の分解（方位との差の三角関数）は、風の材料と走行モデルが同じ値を読む
（`DynamicAxisRequestContext.wind_components_ms`）。合成結果`LegCostArrays`は`cost_lazy`（区間の番号順）と表示用の
`difficulty_array`/`axis_arrays`/`weight_sums`/`material_arrays`（動的材料id→
切り出した区間の順の配列の辞書、`evaluate_dynamic_material_arrays`が返す全材料のうち値がある
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
そのレグの配列から値を読む（探索と表示の一致、[設計原則](../../architecture/design-principles.md)10）。
`RouteSegmentDetail.material_values`/`RouteCandidate.material_values`（重み>0の公開軸が
参照する材料id→値、`AXIS_DEFINITIONS`の`materials`プロパティから導出、
`axis_raw_value.py: displayed_material_ids`が集合を決める）は、動的材料（風等）は`material_arrays`から
（`_material_value_at`）、静的材料（`gradient_percent`）はEdgeごとに計算済みの値を
そのまま読む。`displayed_material_ids`はリクエストの`lens_axis_id`（地図のレンズが表示を
要求している軸）が符号付き材料の軸（`map_value_kind`が`signed_material`）を指す場合、
その軸の材料も重みに関わらず含める（地図の色分けが重み0の軸でも成立するため）。
逆回り候補はレグ割当ても反転する（先に走る側が往路配列、`_reverse_leg_assignment`）。レグ番号は走行順に振られるため、Edge列の反転と同時に番号自体も`max_leg - leg`へ振り直す。探索範囲を覆う格子点ごとの時別風予報
（`WeatherService.get_wind_forecast_lattice`。格子はMSMと同じ細かさ、`domain/wind.py: WindLattice`・
`WIND_FORECAST_LAT_STEP_DEG`/`WIND_FORECAST_LON_STEP_DEG`。格子は緯度・経度0度から数えた固定の線に揃い、
探索範囲に依らない。各Edgeは中点に最も近い格子点の風を引く——ルートを出す前の地図も同じ点を引く、
`_LegCostComposer`の`_wind_points`）が無い場合は、出発時点のスナップショットで合成した1本を全レグで共有する（追加コスト
ゼロ）。**重みが0でも時刻ビンは畳まない**——走行モデル（向かい風は速度そのものを落とす）が
時刻で変わるため、重み0を理由に時刻固定へ落とすと所要時間が狂う。時別系列があれば重みにもレンズにも依らず
時刻で合成し、`lens_axis_id`が効くのは区間に載せる材料の集合（`displayed_material_ids`）だけである。
仮定巡航速度は`RouteGenerateRequest.assumed_speed_kmh`（既定`ASSUMED_SPEED_KMH`）で
リクエストごとに変えられ、通過予定時刻と風の材料`wind_drag_ratio`（走行速度依存）の
両方に効く。迂回率（道なり距離÷直線距離）は定数ではなく実測値を使う。直線距離を走行時間へ直す係数
として使うもので、`prepare`が同じ探索範囲（範囲を覆うz12タイル集合を鍵にする）で前回学習した値
（無ければ`ROUTE_DETOUR_RATIO`）を合成器へ渡す。往路木を求めるたびに実測の中央値
（周回はリングNode、目的地ルートは起点から1km以上の到達Node）を測って
`detour_ratio_cache.set_detour_ratio`へ学習値として保存し（`_median_detour_ratio`・
`_learn_detour_ratio`）、目的地ルートの後ろ向きレグはその場で測った値で到着予定時刻を置く。
**周回の復路レグは迂回率を読まない**——総所要時間は目標距離÷仮定速度で決まる（距離
フィルタが目標±許容を強制する）。運用時は`_build_search_graph`のINFOサマリ
（`wind_time_varying`・`speed_kmh`・`detour_ratio=値(learned|default)`）、
`compose_leg_costs`ログ（`leg`・`mode`・`bins`・`reused_bins`・`compose_ms`）、
`select_turnarounds`/`select_via_nodes`の`detour_ratio_median`で確認できる。

`RouteGenerateRequest.waypoints`/`destination`（経由地・目的地指定）にも対応する
（`api/routers/routes.py: generate_routes`）。

## 戦略層（`route_generator.py: RouteGenerator`）

`RouteGenerator`は`RoadGraphEngine`を直接受け取り、そのメソッド（`prepare`・
`select_loop_turnarounds`・`trace_loop`・`evaluate_loops`等）を呼ぶだけで、探索の内部には
立ち入らない。候補の中身（`TracedLoop.data`）もエンジン固有の形として読まない。

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
        │  idをroute-00..へ振り直す（本数は上の逐次処理がmax_routes件で止めている）
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
1件だけ評価して返す。`POST /api/routes/generate`へ
`spliced_edge_ids`を添えると、折返し点選定・via-node選定を通らずこの経路へ入る
（`destination`必須。合成の対象は目的地ルートだけで、周回は起点へ戻る制約があるため）。

**別エンドポイントにしていない**のは、合成も生成と同じコスト曲線だから——経路は確定済み
でも`prepare`は通る（評価は`_RoadGraphContext`のコスト配列から読む。design-principles.md
構造仕様10）。`prepare`は範囲の切り出しと探索素材の組み立てを毎回行い、区間数に比例して時間がかかるため、
202＋ポーリングのジョブ機構がそのまま要る。

送られたEdge id列が**実在し・順につながり・起点から始まり・目的地へ着く**ことは
`engine.build_traced_from_edge_ids`が確かめ（鍵は`_lazy_index_of`で区間の番号へ戻す。探索範囲に無い・
探索用グラフに載らない区間は実在しない扱い）、成立しなければ`RoutingError`で落とす
（グラフを知るのはエンジンのため戦略層には置けない）。終点は起点と同じ
`find_nearest_node_indexed`で解くため、比べる相手は元の候補が実際に終わったNodeになる
——目的地が孤立していて補正した場合、補正後の地点を条件として返す。
**同じ地点を2度通る列はここでは落とさない**。走れはするので「経路として成立しない」形では
なく、選択肢として出さない側（フロント）で止める。レグは合成経路自身の距離の半分で
切る——via-nodeが無く前向き木・後ろ向き木の境目が存在しないため。

### 較正値（走ってみて決める値）

ターンの秒数・停止要因の待ち・走行モデルの標準値・信号とみなす半径は、いずれも実感に合わせて
置いた値で、較正されていない。**`domain/tuning.py`が唯一の宣言**で、消費者はそこから読む
（定数としても持つと二重になり、片方だけが変わる）。

較正値の宣言は「変えたとき効くまでに何が要るか」（`TuningEffect`）を持つ。これは
**「変えたのに効かない」を宣言として持つ**ためのもので、ほとんどは次のリクエストから効くが、
交差点の値を埋める派生バッチをやり直さないと効かないものもある
（どの値がどの効き方かは`TuningEffect`の宣言が持つ）。

**較正値ではない固定値は宣言へ載せず、使う側のモジュールが値と根拠を隣り合わせで持つ**
——根拠の文はその値の隣にあってこそ読めるもので、宣言へ写すと二重管理になる。載せない理由は
そのまま「なぜ画面から変えさせないか」で、物理定数を出すと模型を壊せ、資源の上限を出すと
本番を止められる。どちらに置くかを機械的に検出する仕組みは無く、数値を1つ置くときに書き手が
この線引きで決める。

宣言そのものの矛盾（idの重複・既定が範囲の外・空の見出し）は`TuningParameter`と
`TUNING_PARAMETERS_BY_ID`の構築がimport時に落とす。重複を黙って通すと後勝ちで消えた側が
画面にも探索にも現れず、範囲外の既定は画面が出した値をそのまま書き戻せない状態になる。

**暗黙の前提**: 値の読み出しは呼ぶたびに行う。プロセス内に束ねる（import時に評価する・
dataclassのフィールド既定値に置く）と、実行時に変えた値が効かない。**プロセスを入れ替えても
直らない**——起動のたびに同じ順序で束ね直すだけで、上書きを読むのは全importの後だからである。
リクエストが省略したときの既定値をAPIスキーマへ書くのも同じ束ね方で、`| None`＋リクエスト
処理時の解決へ倒す（`domain/evaluation.py: resolve_penalty_strength`）。

この前提を守るのは「書いた値がプロセス内の`TUNING_VALUES`まで届く」テストで、母集団は
宣言から導く（`tests/test_tuning_overrides.py`。行が1つも無い状態で全パラメータが宣言の
既定どおりになることを、宣言を走査して確かめる）。値をそのまま読み返せないもの
——上下限として効く値——は、頭打ちになる入力を1つ通して観測する
（`tests/test_cycling_speed.py`）。**フロント側が値を送ってしまうと、この解決そのものが
迂回される**ため、
画面から変える手段が無い値はリクエストへ載せない（`features/route/generationRequest.ts`）。

既定から動かした値は`tuning_overrides`テーブルが**差分だけ**を持つ。行そのものが定義である
`axis_definitions`と違い、**行が1つも無くても宣言どおりに動く**ため、fresh bootstrap
（CI・新規環境・disaster recovery）でスナップショットの投入が要らない。読み込みは起動時と
管理APIの書き込み直後だけで、プロセス内の値を**中身ごと差し替える**（辞書を作り直すと、
import済みの参照が古い辞書を指したままになる）。書き込み直後の読み込みは、書いた後の上書きを
全件読んで宣言の範囲で検算するところまでを**取引の確定の前**に行い、確定の後は差し替えだけにする
（`services/tuning_service.py`）——確定の後に読み直すと、読み出しや別の行の検算の失敗が
「保存は済んだのにエラー」として画面へ返り、動いている値だけが古いまま残る。検算で失敗すれば
書き込みごと取り消される。

壊れた行の扱いは2通りに分かれる。宣言から消えたidの行は**警告して無視する**——パラメータを
1つ減らしただけで本番の起動が失敗するのは割に合わない。値が宣言の範囲の外・数値でない行は
**落とす**——間違った値が静かに効く方が悪い。

較正値には**フロントが使うもの**もある（区間を割る下限等）。ビルド時生成物だけで配ると
管理画面から変えても次のデプロイまで届かないため、`GET /api/axis-catalog`が
いま効いている値を運ぶ（起動時に1回取るものへ相乗りさせ、取得を増やさない）。運ぶ対象は
宣言から導き［効き方が`CLIENT_RELOAD`］、生成物`route-generate-config.json`は
カタログを取れるまでの既定を持つ。

書き込み口は`api/routers/tuning_admin.py`で、軸スタジオと同じ認可境界の内側に置く
（走行モデルの振る舞いを直接変えられるため）。**画面が並べる項目はこのAPIが宣言から導く**
——較正値を1つ足しても、APIにも画面にも書き足す場所は無い。書かせるのは種別が較正値の
ものだけで、範囲の外は422、宣言に無いidは404で断る。応答は各項目の「変えたとき効くまでに
何が要るか」も返し、画面が「変えたのに効かない」を出せるようにする。

### 地点をNodeへ寄せる範囲（`find_nearest_node_indexed`）

寄せてよい範囲には限度がある。**無いと、利用者が指した地点とは別の場所を指定したことに
なる**（呼び出し側は返ったNodeを「指した地点」として扱う）。

- 読み込んだグラフが覆う範囲の外を指した点は寄せない（索引のセル境界＋1セルの余裕で
  判定する。範囲の縁をわずかに外した点は、すぐ隣の道へ寄せる）。
- 目的地が起点から到達できないときの補正（`MAX_DESTINATION_CORRECTION_KM`）は、
  そこから一定距離の中に到達できるNodeが無ければ補正せず、候補なしとして
  `no_candidates_side="destination"`を立てる。

**暗黙の前提**: 述語（起点から到達できるか等）を渡した探索は、それが1つも真にならないと
「見つかった最近傍より外側は必ず遠い」という打ち切り条件が成立しない。索引が占める範囲の
外へ出た時点でも打ち切るのはこのため（実測: 打ち切りが無いと30km規模の索引で16.9分、
その間イベントループを握るためbackend全体が止まる）。

### `generate_via_waypoints`（経由地・目的地指定）

`generate_loops`の折返し点選定・距離フィルタとは独立した経路生成。
`destination`省略時は起点に戻る周回（常に1件）。
距離（`distance_km`）はここでは探索の範囲で、要求の検証（`api/routers/routes.py: RouteGenerateRequest._resolve_distance`）が
置いた点のうち最も遠いものより必ず長く決める——画面は送らず、送られても使わない。

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
  従来どおり`trace_loop`で単一経路を生成する（候補数は指定によらず`route_generator.py:
  applied_max_routes`が`ROUTES_WITH_WAYPOINTS`に決め、生成条件の応答にもその値が載る。画面は同じ値を
  生成物`route-generate-config.json`の`routes_with_waypoints`で受け取る。終点到達後に
  `id="route-destination"`/`direction_label="目的地ルート"`へ上書き、id採番はしない）。

## 候補タブの並び順

`generate_loops`・`generate_via_waypoints`（経由地の無い目的地ルートを含む）とも、
返す`RouteCandidate`一覧を`overall_difficulty`（絶対基準0-100の総合難易度、小数1桁で
比較）昇順（易しい候補が先頭）で並べる。算出不能（`None`）の候補は末尾へ回す。
`generate_loops`は同点（小数1桁が一致）の候補を、評価前に付けた「目標距離に近い順」を
安定ソートで引き継いで並べる——周囲に重みを振った軸のデータが無く全候補のdifficultyが
同じ値になる場合、結果は実質的に目標距離に近い順になる。異なるリクエスト間でも同じ
絶対基準で比較できる。

`generate_loops`は並べた後、idを`route-00..`へ振り直す（本数は折返し点を試す段階で`max_routes`件に達したところで
止めており、並べた後に切る段は無い）
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

- **周回探索（折返し点方式）**: `region.py: bbox_covering_points([origin], radius_km + マージン)`
  （円形の探索半径を包含する矩形、`radius_km = distance_km × TURNAROUND_RADIUS_RATIO`）。
- **waypoints指定（経由地・目的地）**: `bbox_covering_points([origin, *waypoints], 固定マージン)`
  （起点＋全経由地＋目的地を包含する矩形）。

`GraphService.get_search_slice`で探索範囲の区間（`domain/road_network.py: RoadSlice`）と、
その材料から求めた「Edge×公開軸」静的スコア行列（`StaticEdgeScoreMatrix`、行は切り出した区間の順）を
受け取り、`_build_search_graph`が探索用グラフ（`domain/routing.py: LazyRoadGraph`）とbbox全体ぶんの
コスト配列を、`_build_search_structures`が最寄りNodeの索引（`NodeSpatialIndex`）・CSR・ターン構造を
リクエストごとに組む。データ未整備（取込の宣言した範囲の外）ならNoneを返し、呼び出し元
（`RouteGenerator`）が候補0件として扱う。

`_build_search_graph`は、`StaticEdgeScoreMatrix`（風などリクエストごとに変わる動的軸の列は
NaN）へ動的軸（風、`domain/dynamic_materials.py: evaluate_dynamic_axis_arrays`。材料id→evaluator
関数の登録制`DYNAMIC_MATERIAL_EVALUATORS`で軸名をハードコードしない汎用実装）と重み
ベクトルを適用し、`compose_costs_from_axis_matrix`・`compute_hard_filter_excluded`で
コスト配列を1回だけ合成する。合成結果はレグ（往路/復路）ごとに`LegCostArrays`
（`cost_lazy`[区間の番号順]・`difficulty_array`・`axis_arrays`[切り出した区間の順]）へ
まとまり、`_RoadGraphContext.legs`が保持する（下記「レグ別コスト配列」節）。並行Edge
（同一Node間の複数Edge）は、`build_lazy_road_graph`が元の行（切り出した区間の順＝道路網全体の行の昇順）が
最も小さい1本を採る決定的な規則で解消する——コストはリクエストごとに変わるため、トポロジを組む時点では
コストで選べない。同じ`LegCostArrays`は`_build_segment_details`（区間表示）からも区間の番号→切り出した
区間の行（`_slice_row`）で参照され、探索コストと表示の二重計算を避ける。

**走行モデルが読む入力は軸の構成に依存しない**。勾配は静的スコア行列が常に持つ生配列
（0次フィルタの勾配しきい値と同じ列）から、停止の回数は
`domain/traffic.py: stop_count_material_ids`が宣言する材料から読む——「内訳として画面へ
見せる材料」だけを運ぶ既定に任せると、軸を非公開にした瞬間に所要時間の中身が静かに変わる。

### 探索の状態（`domain/routing.py: TurnExpandedStructure`）

一対全最短経路木も2点間探索も、状態を交差点Nodeではなく**有向区間**に取る。交差点で直進したか右左折
したかは「入る区間×出る区間」の対で決まり、Nodeを状態にすると表せないため。ターンの費用は
進入・退出の方位差から秒で決め（`TurnCostSpec`）、そのままコストへ足す（探索のコストも
秒のため換算は要らない）。
加えて、**信号が無く、交差点に集まる道の最大階級が進入した区間より上位で、かつその階級が
そもそも待ちの要る階級（`MAJOR_CROSSING_MIN_RANK`）なら**、横断（直進）・右左折にそれぞれ
費用を足す（`domain/traffic.py: highway_rank`で比べる）。階級の条件が無いと、自転車道
（階級0）からサービス道路（階級1）へ出るだけで「待ちが要る」と判定される。
これは車列の切れ目を待つ時間で、信号のある交差点の待ちとは別物——そちらは停止密度の材料が
走行モデルへ運ぶ（`domain/traffic.py: stop_seconds`）ため、ここで足すと二重に数える
（`docs/architecture/design-principles.md`構造仕様13）。探索側は階級の意味を知らず、比較結果だけを使う。

信号の有無と最大階級は`node_materials`の列で、グラフのノードに載って探索まで届く。
埋めるのは派生バッチ（下記「交差点の信号・最大階級」節）で、**行の無いノードは既定値**
（信号なし・階級0）で読まれる。既定値は安全側に倒れる——信号なしとして扱えば横断の費用が
付き、階級0は読み込んだ部分グラフからの導出を下回るため下限を上げる方向にしか効かない。

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

### 番号と区間の鍵（探索範囲の中の持ち方）

探索範囲の中では、ノードは切り出しの中の番号（`RoadSlice.nodes`の添字）、区間は探索用グラフの番号
（`LazyRoadGraph.edge_rows`の添字、`TracedLoop.data`もこの番号列）で持つ。区間の文字列の鍵
（`edge_id`、`domain/graph.py: edge_key`）とノードの鍵は、**経路に載った区間の分だけ**番号から作る
（`_lean_edge`・`_node_key_of`）——範囲全体ぶんの鍵や区間オブジェクトを作ると、範囲の区間数に比例した
メモリを生成のたびに払うため。クライアントが送り返す鍵（区間の乗り換え）は`_lazy_index_of`が番号へ戻す。
並行区間の採られなかった側・探索範囲の外の区間は番号を持たない（None）。

探索用グラフ・CSR・索引・ターン構造はキャッシュしない（リクエストごとに組む）。範囲ごとに
キャッシュすると範囲の数だけ常駐が積み上がり、コンテナのメモリ上限へ届くため。範囲をまたいで
持つのは、探索範囲（範囲を覆うz12タイル集合）ごとに学習した迂回率（実数1個、
`infrastructure/detour_ratio_cache.py`、「レグ別コスト配列」節）だけである。

`_reverse_traced_edges`（逆回り候補、後述）は、経路上の各区間の逆向きを
`domain/routing.py: edge_index_between`（CSRの行を二分探索）で引く。

### `select_loop_turnarounds`（折返し点選定）

起点からの一対全Dijkstra（`domain/routing.py: build_turn_expanded_tree`、軸重み付き
コスト、コスト上限で打ち切り）を1回求め、木に沿った往路の実距離が目標の半分付近に入る
Nodeを「リング」として抽出する。**距離は最短実距離ではなく軸コスト最適経路の実距離で
定義する**——重みを極端に振った設定ほど往路が遠回りするため。

並びは往路の距離加重平均difficulty（`overall_difficulty`と同じ物差し）の昇順、同点は
リング中心に近い順。**リング中心は上下限の算術平均ではなく目標距離から決める**——許容が
目標以上で下限が0へクランプされる場合、算術平均だと中心が0付近まで下がる。

同点の候補は`select_diverse_by_overlap`へグループ（`tie_groups`）として渡し、グループ内の
試行順は最遠点貪欲法（採用済み候補との方位の角距離の最小値が最大の順、1件採るたびに
決め直す）で決める。**方位は生成機構ではなく同点タイブレーク専用**で、比較対象が採用済み
候補だけのため計算量は走査件数×採用件数に留まる。difficulty群自体の順序・同点でない
候補間の順序はこの並べ替えでは変わらない。

`select_diverse_by_overlap`は上位から、既採用候補と往路が重複しすぎるもの・近すぎるものを
飛ばして`pool_size`件採る（埋まらなければ重複の条件を緩めてやり直す）。しきい値は
同ファイルの定数が持つ。

### `trace_loop_from_turnaround`（復路探索）

往路は一対全木上の経路そのもの（`turn_expanded_path_edge_indices`で復元、A*での再探索はしない
——同じコスト配列でA*をかけ直しても同じ経路になるため）。復路探索の間だけ、往路Edge＋
同一Node対の逆方向Edgeのコストを共有`cost_lazy`上で`RETRACE_PENALTY_MULTIPLIER`倍へ
**差し替え**（infにはしない——復路が往路を戻る以外に道が無い区間[袋小路等]は通れる必要が
ある）、A*（復路の目的地は常に起点のため、ヒューリスティック配列はリクエストで1回だけ
計算し全候補で共有する）で探索した後、`try`/`finally`で元の値へ復元する。この差し替えはawaitを挟まない同期区間で完結し、復路探索が同期・直列実行
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
   `find_nearest_node_indexed`は条件（`predicate`）を満たすNodeが1つも無ければ索引の
   範囲を使い切ってNoneを返すため、候補が1つも見つからないのは
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
順にA*で結ぶ（`bearing=None`固定、戻り値の`data`は経路上の区間の番号列）。

### `evaluate_loops`（実ジオメトリ取得・評価）

距離フィルタを通過した全候補ぶんの区間（番号から`_lean_edge`で作った形の無い枝）を1つにまとめ、
`GraphService.get_edges_with_geometry`を**1回のクエリ**で呼んで実ジオメトリを取得する（棄却済み候補への
DB問い合わせを避ける2段階分割を維持したまま、候補ごとには問い合わせない）。
取得後は候補ごとに`_build_best_candidate`を`asyncio.gather`で並行評価する（標高取得・
segments構築はEdge単位の軽量な計算のため並行化してよい。復路探索のような共有状態の
書き換えを伴わない）。`_build_segment_details`は、探索コスト算出時に`prepare`が既に
合成済みの`LegCostArrays`から値を読み（ビンが2本以上あるレグは上記「レグ内の時刻ビン」のとおり
経路上の行だけを合成し直す）、`RouteSegmentDetail`列へ組み立てる（標高・路面等の表示専用
フィールドはEdge単位の軽量な計算のまま）。

**戻り値は入力の`traced`と同じ件数・同じ順**（位置で対応づける契約）。戦略層は
`TracedLoop.data`の中身を知らないため、どの候補がどの`TracedLoop`由来かを位置以外で
突き合わせられない（基準線への印付けがこれに依存する）。件数のずれは
`RouteGenerator._evaluate_and_aggregate`が`RoutingError`で落とす——ずれても候補が消えるわけでは
なく、印・ラベルだけが静かに入れ替わるため結果からは気づけない。

### `_build_best_candidate`（逆回りループ候補の代数的合成）

周回候補（waypoints指定でない場合）は、順方向の探索結果から逆方向候補を
**追加のDB/API呼び出し無しに代数的に導出**する: 標高の獲得/喪失を入れ替え、勾配の符号を
反転し、既にhydrate済みのgeometryを再利用する（`_reverse_traced_edges`/
`_reverse_elevation_attribute`・`_reverse_elevation_by_edge`）。両方向の`distance_weighted_difficulty`を比較し、
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

探索範囲の道路網を、取込範囲全体の配列（`infrastructure/road_network_store.py`）から**切り出すだけで、
作らない**。道路網は取込・派生バッチ（[静的道路属性・タイル配信](static-road-attributes.md)）が取込範囲
全体ぶん先に作り、配列の置き場はバッチとデプロイの前処理が作る（下記「道路網全体の配列」節）ため、
ここには「無ければ作る」経路が無い。外部（Overpass等）へのフォールバックも持たない。

### 取得の入口（`get_search_slice`）

1. **カバレッジ判定**: `RoadGraphRepository.is_covered`が、bboxが取込の宣言した範囲
   （成功した`osm_way`取込の`source_runs.profile`のtarget.bbox）に触れるかを1クエリで判定する。
   範囲外ならNone（WARNING常時ログ）。マーカーの表は持たない——持つと取込範囲を広げたときに
   2箇所を揃える必要が生まれる（判定式は路面タイルのMVT生成と共有、下記「派生delivery系
   クエリ」）。
2. **切り出し**: bboxに、区間の形の外接矩形が重なる区間を取り出す
   （`domain/road_network.py: slice_network`。範囲の外へはみ出す区間も端点ごと含む）。道路網は
   `road_network_store.current()`が返すプロセス内で1つの配列で、生成のたびに増えない。あわせて
   bboxを覆うz12タイルの集合を返し、学習した迂回率の鍵にする（近い範囲の生成が同じ鍵を共有する。
   切り出しの範囲そのものはタイルに揃えない）。
3. **読み込む量の上限**: 切り出した有向の区間の数が上限を超えれば`SearchAreaTooLargeError`を送出する
   （WARNING常時ログ）。探索用グラフ・コスト配列・ターン構造・候補の評価は区間の数に比例してメモリを使い、
   backendのコンテナの上限を超えるとプロセスごと落ちて全員の生成と地図が止まるため、1回の生成が組む量を
   ここで抑える。上限は定数で持たず、コンテナのメモリ上限（cgroupの`memory.max`、`container_memory.py`）から
   「（メモリ上限 − 生成以外への取り置き）÷ 同時に動く生成の数（`generate_max_concurrent`）÷ 1本あたりの
   メモリ」で導く——メモリを増やすときに直すのはデプロイのメモリ上限の1か所だけで、上限はそれに付いてくる。
   1本あたりの値は、本番と同じ上限の使い捨てコンテナで都心の40・60・80kmを2件同時に流し、cgroupの退避できない
   メモリ（anon）の最大を切り出した区間の合計で割った値の最大（約1.0KB）から決めてある。探索・評価の
   配列の持ち方を変えたら測り直す。取り置きは本番の常駐分（地図タイルの配信を含む）に余裕を見た値。
   上限が付いていない環境（開発機）では断らない。区間確認API（`/api/routes/preview`）は生成の同時実行の枠の
   外で動くため、枠いっぱいの生成と重なったときは取り置きから使う。
   戦略層（`RouteGenerator._prepare`）はこの例外を「探索範囲の道路が多すぎる」理由付きの候補0件に、
   区間確認APIは422にする。
4. **静的スコア行列**: 切り出した区間の材料（`material_arrays_of`、分類の材料は語彙の値へ戻す）から
   `build_static_edge_score_matrix`で求める。キャッシュしない——軸定義の編集がそのまま次の生成に効き、
   軸定義の世代を突き合わせる仕組みが要らない。

戻り値は`(RoadSlice, StaticEdgeScoreMatrix, タイル集合)`。スコア行列の行は切り出した区間の順。

`get_edges_with_geometry`は確定した経路の区間へ形を後付けする（リポジトリへそのまま委ねる）。
`RoadGraphEngine.evaluate_loops`が距離フィルタ通過候補ぶんの区間をまとめて1回・
`preview_segment`が1回、いずれも逐次に呼ぶ。

## domain層

### `domain/routing.py`

- `LazyRoadGraph`/`build_lazy_road_graph`: 探索用グラフ。区間の始点・終点（ノード番号）の配列から組み、
  区間の番号（`edge_rows`の添字＝探索の状態）は`(始点, 終点)`の昇順に並ぶ。`edge_rows`が番号→元の行
  （切り出した区間の順）を結ぶ。探索はコストをnumpy配列のまま受け取る（探索中に
  Pythonのコールバックを作らない設計の核心）。並行Edge（同じnode対の重複辺）は元の行が最も
  小さい1本を採る決定的な選択で解消する（コストはリクエストごとに変わるため、コストでは選べない）。
  区間の両端は切り出し（`slice_network`）が必ずノードの行を持つ形で作るため、ここでは確かめない。
- **`CsrGraphStructure`/`_build_csr_structure`・`SearchGraphStatics`/
  `build_search_graph_statics`**: `LazyRoadGraph`と同じNode/区間の番号を持つ
  CSR（圧縮行格納）**構造のみ**（Edge重みは持たない）。区間の番号が既に`(始点, 終点)`の昇順のため、
  行ごとの範囲を数えるだけで組め、各行の中は終点の昇順になる（`edge_index_between`がこの並びを
  二分探索して、両端のノードから区間の番号を引く）。`SearchGraphStatics`は
  この構造とEdge実距離配列（m）を束ねる。**どちらも転置は返さない**——逆向きが要るのは
  Nodeではなく辺基準の遷移で、そちらは`TurnExpandedStructure.reverse_transitions()`が
  最初に必要になった時点で1度だけ作って保持する。`indptr`/`indices`/
  `entry_edge_index`はint32（実データ規模のNode/Edge数はint32の値域に
  対して桁違いに小さい）。辺基準グラフの遷移は`build_turn_expanded_structure`が
  この3配列から導くため、Node対からCSRエントリ位置を引き直す整列キーは持たない。
- **`TurnCostSpec`/`TurnExpandedStructure`/`build_turn_expanded_structure`**:
  状態＝有向区間・辺＝ターンの遷移構造（「探索の状態」節参照）。`CsrGraphStructure`と
  同じくEdge重みは持たず、遷移とターンの秒だけを持つ。グラフを物理的に展開せず遷移を
  `CsrGraphStructure`から導く。
  `edge_bearings`（区間の方位。折れ線から求めた値が無い区間だけ両端Nodeの座標から補う）・
  `_turn_seconds_for`（方位差→秒）が入力になる。
  **ターンの費用に効く入力はすべて引数で必須**——既定を持たせると、渡し忘れが
  「上位の道の横断に待ちが付かない」構造を黙って作る。
- **`TurnExpandedTree`/`build_turn_expanded_tree`**: 起点からの一対全Dijkstra
  （numba、前任者付き、`cost_limit`で打ち切り可能）。実距離と素の所要時間は緩和のたびに
  そのまま積むため、前任者を遡り直す積算が要らない。状態ごとの値に加え、Nodeごとの
  値（そのNodeへ入る区間の最小）も持つ。素の所要時間の配列は引数で必須（無いと経過時間を
  コストで測ることになる）。**時刻ビンが2本以上あるのにビンの幅が欠けていれば`ValueError`**
  （`turn_expanded_shortest_path`と共通）——欠けたまま走ると全状態が先頭のビンへ落ち、
  時刻ごとの風が黙って効かなくなる。コスト配列と所要時間配列の形の不一致も同様に断る
  （JITした探索は配列の境界を検査しない）。
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
- **JITのコンパイル（`compile_search_kernels`・`_kernel_array`）**: 一対全木と2点間探索のJITは`cache=True`で、
  コンパイル結果を`routing.py`の隣の`__pycache__`に置き、別のプロセスはそこから読む。イメージの組み立て
  （`backend/Dockerfile`）が`compile_search_kernels`（最小の道路網で両方を1回ずつ呼ぶ）で焼き、入れ替えた
  コンテナの最初のルート生成はコンパイルを待たない。numbaは引数の型（dtype・並び・読み取り専用か）ごとに
  別々にコンパイルするため、探索の入口（`build_turn_expanded_tree`・`turn_expanded_shortest_path`）はJITへ渡す
  配列を`_kernel_array`で1つの型へ揃える——揃えないと、焼いたものと型の違う呼び出しが本番で初めてコンパイルを払う。
  **生成の経路がPythonから呼ぶJITは、`compile_search_kernels`が呼ぶ探索の2本だけにする**——焼くのはそこで
  Pythonから呼んだものだけで、探索の中へ展開する部品をPythonから直接呼ぶと、その部品だけ各コンテナの最初の
  生成でコンパイルを払う。探索と表示で共有する`time_bin_of`は素の関数とし、探索の中ではそれをJITした
  `_time_bin_of_kernel`を展開する。
  キャッシュが効く条件（CPUの型・元のファイルの更新時刻）は[tech-stack.md](../../architecture/tech-stack.md)
  「デプロイの反映確認」節。
- **`_empty_heap`/`_heap_push`/`_heap_pop`/`_grown`・`_time_bin_of_kernel`**: 一対全木と2点間探索が共有する
  `@njit`の部品。ヒープの列は「順位のキー・状態」と、**キーが`g`と別の値になる探索だけが持つ**
  「積んだ時点のコスト`g`」。A*はキーに`g＋下界`を積むため`g`の列を持ち（`best[state]`は
  最新の`g`で、積んだ時点の`g`とは別物なので省けない）、Dijkstraはキーが`g`そのものなので
  列を持たず、`_heap_push`へ`g`を渡さない（取り出しはキーを`g`として返す）。ヒープは列と
  「`g`の列を持つか」の組（`_Heap`）で持ち、列の有無を容量や配列の長さから推さない。部品は1組
  だけにする。容量は最低1にする（伸長は要素数を倍にするため、0からは伸びない）。
  `_heap_push`は満杯なら倍へ伸ばした組を返すため、呼び出し側は戻り値の組で持ち替える。
  `_time_bin_of_kernel`は経過時間が落ちる時刻ビンを端へ寄せて返す（区間の表示も経路をたどって同じ本体の
  `time_bin_of`で同じビンを選ぶ）。
  **部品はどれも`inline="always"`で呼び出し元へ展開する**——関数呼び出しのまま残すと、
  押し込み・取り出しのたびに配列を束ねた戻り値の受け渡しが乗り、合成グラフ（70万状態）での
  一対全木・2点間探索がどちらも約2割遅い。Dijkstraにも使わない`g`の列を持たせる形は、
  同じ条件で一対全木が約1割遅い。
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
- `RoadGraphEngine.is_loop_too_similar`（`_loop_edge_lengths_by_
  physical_segment`）: 距離フィルタ合格後の候補が、既に採用済みの候補と周回全体
  （`TracedLoop.data`、往路＋復路の区間の番号列）で`LOOP_MAX_OVERLAP_RATIO`（0.7、往路のみ
  比較する`TURNAROUND_MAX_OVERLAP_RATIO`＝0.6より緩め）を超えて重複するか判定する。
  区間を両端のノード番号のfrozensetへ正規化し進行方向を無視して比較する
  ため、「同じ周回の逆回り」・「往路は違うが復路が同じ裏道へ収束する」周回のどちらも
  同じ判定で弾ける。
- `NodeSpatialIndex`/`build_node_spatial_index`/`find_nearest_node_indexed`:
  グリッドバケットによる最近傍ノード探索。ノードの座標配列から組み、候補（ノード番号順の真偽）を
  渡すとそのノードだけを載せる。戻り値はノード番号。
- `compute_routable_nodes`（`domain/hard_filters.py`）: 最近傍ノード探索は「0次
  ハードフィルタを通過したEdgeが最低1本残るノード」だけに制限する（制限しないと孤立
  ノード——幹線道路にしか面していない駅等——が最近傍として選ばれ、経路探索が失敗しうる）。
  lazy評価ではEdgeコストを事前計算しないため、Hard Constraintだけを軽量に評価する
  専用関数として0次フィルタのモジュール（`domain/hard_filters.py`）に置く
  （`domain/routing.py`側には持たない）。
  入力は区間の始点・終点と、`compute_hard_filter_excluded`が返す`excluded`配列
  （`_build_search_graph`がコスト配列を`inf`にするのに使うのと同じ配列）で、ノード番号順の真偽を返す。

### `domain/graph.py`

- `LeanEdge`（dataclass）は**確定した経路の区間の分だけ**作る向きを持つ枝（A→BとB→Aは別の枝）。
  探索は区間の番号で動き、このオブジェクトを作らない。DBの区間を指す`(osm_way_id, segment_index, forward)`は
  必ず持つ（形を取り直すときの鍵）。`geometry`は作った時点では空リストで、
  表示のために`get_edges_with_geometry`が取り直して埋める。
- 区間とノードの文字列の鍵（`edge_key`・`node_key`）と、区間の鍵の読み戻し（`parse_edge_key`）は
  ここだけが持つ。路面タイルのフィーチャーの鍵（向きを持たない区間。`edge_feature_key_sql`・
  `parse_edge_feature_key`）も同じ場所に置く——`edge_key`とは別の鍵で、タイルのSQLが組み立て、
  区間インスペクタが読み戻す。APIが運ぶ鍵とDBの`(osm_way_id, segment_index, forward)`の対応がここで決まる。

### `domain/route.py`

- `Coordinates`・`RouteSegment`・`RouteSegmentDetail`（**material_valuesに入る
  符号付き材料（`gradient_percent`等）は符号付きが正準契約**——絶対値ではない。
  frontend`routeStyleModes.ts`がこの契約に依存する）・`RouteCandidate`。
- `aggregate_segments_into_bins`（500m区間ビニング）・`merge_axis_difficulties`・
  `merge_axis_contributions`・`merge_axis_raw_values`・`merge_material_values`・
  `merge_material_category_shares`・`_merge_segment_bin`。**`RouteSegmentDetail`の
  フィールドは、ビンへの畳み方（`BIN_FIELD_MERGERS`）を必ず宣言する**。`_merge_segment_bin`は
  この表だけからビンを組み立て、辞書フィールドの畳み方（キーごとの距離加重平均、
  `BIN_DICT_FIELD_MERGERS`）も、形・位置・距離のように個別に畳むものも同じ表に載る。
  ビンへ引き継げない値（平均できない分類値等）はこの器に載せず、ビニングの前に
  候補全体へ畳む（`merge_material_category_shares`）。宣言の無いフィールドは
  `domain/route.py`の読み込み時に落ちる——放っておくと、型でも例外でも現れないまま
  APIからは「そのフィールドだけ既定値（空・null・0）」に見える。母集団は型を問わずモデルの
  全フィールドから引き、表のキーを引く（型で絞ると、`dict[...] | None`や既定値つきの
  数値・文字のフィールドが静かに外れる）。
- **`RouteCandidate.edge_point_offsets`は、その経路のEdgeが`geometry.coordinates`の
  どこで切り替わるか**を`edge_ids`より1件多く持つ。隣接Edgeの境界点は重複させずに連結する
  （`_concat_edge_geometries`）ため、**座標列だけからはEdgeの境目を復元できない**。
  Edge単位で決めた区間を地図へ帯として描くのに要る。座標列と境界の位置は同じ関数が
  同時に作る——別々に組み立てるとずれても型でも例外でも現れず、帯だけが1点ずれる。
- **`RouteCandidate.node_ids`は経路が通るNodeを`edge_ids`より1件多く持つ**
  （`node_ids[i]`が`edge_ids[i]`の始点、末尾が終点）。**候補どうしが同じ地点を通るかを、
  座標の一致ではなくグラフの同一性で判定できる形で配る**ためにある——乗り換えを鎖で
  伸ばすほど、その判定が結果を左右する。
- **`RouteCandidate.edge_ids`は畳む前の経路そのもの**（`_build_candidate`が
  `edges_in_path`から起点順に載せる）。`segments`は約500m単位へ畳まれてEdgeと1対1に
  ならないため、経路の同一性を判定できるのはこちらだけ。**乗り換え後の経路もこのidの列で
  受け取って評価し直す**——ステートレスのため、経路の指定はこの形でしか受けられない。
- **categorical材料の延長割合はビニングより前に畳む**。ビンの代表値を1つ選ぶ形だと割合が
  500m単位へ量子化されるため、`road_graph_engine`が`aggregate_segments_into_bins`の前に
  `merge_material_category_shares`を呼び、結果を`RouteCandidate`へ載せる。
  `route_generator`の後段はこの値に触らない（触ると、区間側が空になっている以上
  必ず`{}`で上書きされる）。
- **生値・材料値に無限大は来ない**。材料の値式は区間の長さが0なら割らずに欠損にし
  （`domain/material_catalog.py`・`material_sql.py`の密度の式）、動的材料（風）は定数で割り、
  生値は材料の値と参照先の軸の得点の重み付き和である。欠損（NaN）は区間を組み立てる`road_graph_engine`が落とす。
  有効数字の丸め（`_round_significant`）が非有限値をそのまま返す分岐は、この前提の下では通らない。

### `domain/geo.py`・`domain/errors.py`

`geo.py`は球面三角法の地理計算——2地点の球面距離と初期方位角、それを多数の地点へまとめて求める配列版、
角度から方位の呼び名への変換（例: `haversine_distance_km`・`compass_label`）——を持つ。`LatLon`（`Protocol`）・
`LatLonPoint`（`NamedTuple`）は`Coordinates`（Pydantic、API境界の入力検証用）を経由
せずに緯度経度を扱うための軽量な構造的型で、最近傍ノード探索のような
ホットパスがバリデーションコストを避けるために使う。

`errors.py`は`RoutingError`と`SearchAreaTooLargeError`を持つ。`RoutingError`は
`RoadGraphEngine`・`RouteGenerator`が経路探索の失敗を表すのに共通で使う。
`SearchAreaTooLargeError`は経路が無いのではなく読み込む範囲が広すぎることを表し、
`RoutingError`とは別の型にしてある——利用者へは「範囲を狭めれば作れる」と伝えるため、
経路の失敗と同じ扱い（候補ごとの失敗として数える・502）に混ぜない。

## infrastructure層

### `road_graph_repository.py`（読み出し専用のリポジトリ）

`RoadGraphRepository`は1つの`AsyncSession`を使う1クラスで、**読むだけ**である。書き込むのは
`app/batch/`の取込（`ingest_cli.py`）と派生（`derive_cli.py`）だけで、web側に「無ければ作る」
経路は無い（表の宣言は`derived_models.py`・`source_models.py`、[静的道路属性・タイル配信](static-road-attributes.md)
の管轄）。

区間（`road_edges`）は**向きを持たない1本1行**で、有向の枝は道路網全体の配列を作るときに組む
（`road_network_store.py`。一方通行は`way_materials.direction`を見て走れる向きの枝だけを
作る）。DBへ向きを伝えるのは`(osm_way_id, segment_index, forward)`の3つ組で、向きで変わる値
（方位・標高）はSQLが入れ替え・符号反転して返す（`reversed_material_expression`）。材料の値の
求め方は`domain/material_sql.py`・`domain/material_catalog.py`が持ち、リポジトリは式が前提に
する別名（`w`/`re`/`em`/`wm`）のFROM句を組み立てるだけで式を書かない。

探索用グラフは形を持たない。実ジオメトリが要る確定した経路だけを
`get_edges_with_geometry`が取り直す（逆向きの枝は形状点列を逆順にする）。

**道を結合して区間を範囲で絞るSQLは、区間の空間索引だけで絞る**——道の側からも範囲で絞ると、
プランナが道を外側にした入れ子ループを選んで遅くなる。

#### 派生delivery系クエリ（wind/gradient/road surface/POI）

`_ROAD_SURFACE_TILE_MVT_SQL`（路面・道路種別・車ストレス材料タグ等をPostGIS側で
ST_AsMVT丸ごと生成）・`_FEATURE_MIDPOINTS_IN_TILE_SQL`（wind、道路自身の方位角は使わず鍵ごとに
中ほど＝両端の平均の緯度経度を返す。区間の中ほどは探索の`mid_lat`/`mid_lon`と同じ点）・`_FEATURE_GRADIENT_INPUTS_IN_TILE_SQL`（gradient。そのフィーチャーに属する
区間の値を長さで重み付けて平均する——区間単位のズームでは区間1本の値そのもの、way単位の
ズームではwayの全区間をならした値になる。区間の勾配はジオメトリの始点→終点を正とするため、
フィーチャーの基準方位とのcosの符号で向きを揃えてから平均する）は、いずれも
`_COVERAGE_SQL`（取込の宣言した範囲か）をMVT生成と同じ1クエリへ畳み込み、1タイル1DB往復に
まとめる設計を共有する。カバレッジ外はNone、カバレッジ内で0件なら空、という契約で呼び出し側
（`RegionService`）が空タイルと区別する。いずれも**同じ`_TILE_FEATURE_SOURCE_SQL`から
フィーチャーを引く**——別々に組み立てると、代表の選び方がタイルとずれた瞬間に鍵が噛み合わず
色が一切付かない。詳細は[dynamic-way-values.md](dynamic-way-values.md)参照。

**material_catalogの動的値列挙**（`get_distinct_material_values`）: 軸スタジオ
（AxisComposer.tsx）がhighway/surface/smoothnessのような開放的な多値材料の候補一覧を
動的取得するための経路。値式（`MaterialSpec.value_sql`）は`domain/material_sql.py`の共有断片を
`_ROAD_SURFACE_TILE_MVT_SQL`・`material_coverage.py`
（[evaluation-scoring.md](evaluation-scoring.md)）と共通で参照する。詳細は
[axis-studio.md](axis-studio.md)参照。

### 道路網全体の配列（`road_network_store.py`）

取込範囲全体の道路網（有向の区間とノード、区間ごとの材料）を列の配列として1つ持ち、ディスクの
`data/road_network/<形の署名>-r<派生データの世代>/`へ置く。**DBから作るのに数分かかる**（本番の
有向500万本で、材料の読み出しだけで約3分）ため、作るのはデータを書くバッチの入口（`run_batch_cli`が
世代を進めた直後）と、デプロイの前処理（`scripts/build_road_network.py`、旧コンテナを止める前）だけに
する。どちらも、今の世代・今の形の置き場が既にあれば作らない。

形の署名は`RoadNetwork`の列と読み出しのSQL（材料の式を含む）から導く——材料の式を変えたコードの
デプロイでは署名が変わり、前処理が新しい置き場を作る。作ったときは同じ署名で世代の古い置き場を消し、
**署名の違う置き場は消さない**（入れ替え前の旧コンテナがそれを読んでいる）。

材料は`get_edge_material_arrays`で引き、式はタイル配信・軸スタジオと同じ`domain/material_sql.py`の断片を
使う（材料の式を2か所に持たない）。端点のノードが無い区間は落とす（道の行が無い区間は読み出しの結合で
既に落ちている）。

backendは置き場を読むだけで、読むのは`current()`の1か所である。呼ぶたびに置き場を見て、読み込み済みより
新しい世代（バッチが作り直した）があれば読み直す——読むのは配列をメモリマップで開くだけなので、
見るたびの費用はディレクトリの一覧程度。今の形の置き場が1つも無ければ`RoadNetworkUnavailableError`を送出する
（生成は失敗する。作るのは前処理かバッチ）。起動後に、今の形の署名でない置き場を消す（`prune_other_shapes`。
入れ替わるまでは旧コンテナが読んでいるため、起動後にだけ消す）。

### キャッシュ（ルート生成はRedisを使わない）

ルート生成の経路で使うキャッシュはプロセス内メモリとディスクだけで、Redisを経由しない。

| 層 | 対象 | 実装 |
|---|---|---|
| プロセス内（1つだけ、全リクエストが共有） | 道路網全体の配列（メモリマップ） | `road_network_store.py: current` |
| プロセス内（件数上限LRU） | 探索範囲ごとに学習した迂回率 | `detour_ratio_cache.py` |
| ディスク | 道路網全体の配列（プロセス再起動をまたぐ。世代ごとの置き場） | `road_network_store.py` |
| ディスク | 標高DEMタイル | `tile_cache.py` |

探索用グラフ・CSR・索引・ターン構造・静的スコア行列はキャッシュせず、生成のたびに切り出しから組む。
範囲ごとに持つと、範囲を変えながら生成が続くだけで常駐が積み上がるため。

カバレッジ判定（`is_covered`、`source_runs`への1クエリ）はキャッシュせず毎回PostGISへ
問い合わせる。エッジの実ジオメトリ（`get_edges_with_geometry`）も同様に毎回読む。
判断をキャッシュしない理由は[docs/conventions/caching.md](../../conventions/caching.md)参照——別プロセスのバッチが
取込の記録を書き換えるため、判断を保持すると古い範囲で答えうる。派生データそのものの
書き換えへは、道路網の置き場の世代（バッチが世代を進めた直後に作り直す）で追随する。

## API（`api/routers/routes.py`）

| エンドポイント | 内容 |
|---|---|
| `POST /api/routes/preview` | 2点間の単純なルート取得（`get_preview_builder`経由。`RoadGraphEngine.preview_segment`を使う。`RouteGenerator`の周回戦略は使わない。重み・換算レート（P）はリクエストで上書きできず、ルート生成が省略時に使うのと同じ既定で探す。2点を覆う範囲の区間が読み込む量の上限を超えれば422） |
| `POST /api/routes/generate` | 202を即座に返す非同期ジョブ投稿。`asyncio.create_task`でジョブ本体（`_run_generate_job`）を起動し、タスク参照を`_running_generate_tasks`が保持する（`BackgroundTasks`だとレスポンス送出の失敗でジョブが起動せず、投稿時点で取得済みのセマフォが解放されない） |
| `GET /api/routes/generate/{job_id}` | ジョブの状態・結果を取得（`job_registry`、サーバー再起動で失われる） |

- **同時実行数の制限**: `generate_routes`ハンドラ内で`_generate_semaphore.locked()`
  確認と`acquire()`をawaitを挟まず連続実行する（HTTPレスポンス送出という実I/Oを挟んでから
  acquireすると、複数リクエストが同時に届いた際に上限を超えて受理してしまうため）。
  セマフォの解放は`_run_generate_job`側の`finally`で行う。
- **バックグラウンドジョブはリクエストスコープのDBセッションを使えない**。
  `api/dependencies.py: open_route_generation_setup`（`@asynccontextmanager`）がDI用の
  ジェネレータをラップして独立したセッションを開く（開閉のロジックを複製しない）。
  「どのサービスをどう組み立てるか」自体は純粋関数`_assemble_route_generation_setup`へ
  一本化してあり、DI経由の経路とバックグラウンドジョブの両方が同じ組み立てを通る。
- **`RoutePreferenceWeights`/`HardFilterOverride`は「上書きするなら全項目を明示する」
  方針**（`model_validator`でキー集合の完全一致を強制）。`RoutePreferenceWeights`の
  対象は`AXIS_DEFINITIONS`の公開軸のみ（内部軸は含まない）。
- ジョブ失敗時、クライアントへは汎用メッセージのみ返す: 例外の生メッセージ
  （PostGIS/内部処理のエラー詳細を含みうる）は`logger.exception`でサーバーログに
  のみ残す。

## 交差点の信号・最大階級（`batch/derive_node_materials.py`が埋める）

ターンの費用が読むノードの値（`node_materials.has_traffic_signals`・`max_highway_rank`）は
派生バッチ`derive_node_materials.py`が埋める（バッチ自体は[静的道路属性・タイル配信](static-road-attributes.md)
の管轄。ここには探索側から見た前提だけを書く）。行の無いノードは道路網全体の配列を作るときに
既定値（信号なし・階級0）で読む。

**信号の有無はノード単位でしか表せない**。ターンの費用は「進入した道より上位の道と交わる
交差点」で秒数を足すが、信号での待ちは停止密度の材料が走行モデルへ運ぶ
（`domain/traffic.py: stop_count_material_ids`）ため、そこと重ねると二重になる。ターン側が
足すべきなのは信号が無いのに上位の道を渡る・そこへ入るときの待ちで、Edgeへ畳み込むと
どちらの端の信号かが失われて区別できない。

信号は交差点そのもののノードではなく流入路ごと・横断歩道位置ごとの別ノードとして描かれる
ため、判定は`osm_node_id`の一致ではなく半径（`derive_node_materials.py: SIGNAL_RADIUS_M`）で
行う。**半径は結果を大きく動かす**——広げるほど「信号あり」とみなすノードが増え、そのぶん
ターンの費用が下がる（幹線が集まる交差点で信号ありとみなす割合は、10mで37.4%・60mで67.9%まで
変わり頭打ちが無い）。較正されていない値である。

**暗黙の前提**: この半径は、同じ交差点の点をまとめる距離（`POI_CLUSTER_EPS_M`）とは別の定数
として持つ。問うていることが違う（あちらは「同じ停止か」、こちらは「この交差点に信号があるか」）
ため、まとめる距離を較正で動かしたときに横断の費用まで一緒に動いてはいけない。

`max_highway_rank`はDB全体から見た値で、探索は読み込んだ部分グラフからも同じ値を導ける。
DB側の値は**その下限を上げるためだけ**に使う（bboxの外へはみ出した上位の道を取りこぼさない）
——既定値の0でも探索側の導出が働くため、バッチが埋めていないノードでも挙動は変わらない。

## 暗黙の前提のまとめ

- **夜間の判定は出発時点1点で決まる**: 出発地点・出発時刻の昼夜判定をルート全体へ
  一様適用する。風は上記「レグ別コスト配列」のとおりEdgeごとの通過予定時刻で引くが、
  風の場所の違いは予報の格子（MSMと同じ細かさ）までで、それより細かい差（谷筋・ビル風）は入らない。時刻はレグごとに
  最大`MAX_TIME_BINS`本のビン（1時間刻み）までしか追わず、その先の区間は最後のビンの予報を使う
  （区間の風の`extended`）。
