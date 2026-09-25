# 評価・スコアリング（backend）

## 責務

道路のEdge/区間から、0次フィルタ判定・軸別difficulty・合成difficulty・探索用cost・
候補集合内の相対スコアを算出する。軸ごとの評価式自体（`AxisDefinition.shape`の評価）は
[軸スタジオ・評価軸定義](axis-studio.md)が持ち、本モジュールはその1段上（材料の解決・
複数軸の合成・0次フィルタ）を担う。

**対象ファイル**

| レイヤー | ファイル |
|---|---|
| domain | `evaluation.py`（Edge Costの算出。スカラー／ベクトル／タイル静的行列の3表現）・`hard_filters.py`（0次フィルタ）・`route_preference.py`（重み指定）・`dynamic_materials.py`（風などリクエスト時に決まる材料）・`axis_inspector.py`（区間インスペクタ）・`difficulty.py`・`material_catalog.py`・`material_sql.py`（材料の値をSQLで導出する式と、道・ノードの生データの読み方） |
| services | `evaluation_service.py`・`material_coverage_service.py` |
| infrastructure | `material_coverage.py`（材料ごとの欠損割合の集計クエリ） |
| api | `material_catalog.py`（材料カタログ・材料値一覧・欠損割合のエンドポイント） |

domainのファイルは**変更理由で分けてある**。`evaluation.py`が変わるのはコストの
計算方法を変えるとき、`hard_filters.py`はフィルタを増減するとき、`route_preference.py`は
APIが受け取る重みの形を変えるとき、`dynamic_materials.py`は動的材料を増やすとき、
`axis_inspector.py`は区間インスペクタの内訳表示を変えるとき。

`material_sql.py`が**domainにある**のは、材料が何から導かれるかがdomainの知識だから。
[routing-engine.md](routing-engine.md)の`_ROAD_SURFACE_TILE_MVT_SQL`と本モジュールの
`material_coverage.py`が同じ式を参照する——infrastructureの各所がそれぞれSQLを書くと、
一方だけ変わったときに気付けない。

**材料の導出は`MaterialSpec.value_sql`1本**。評価・地図タイル配信・欠損率の集計・
軸スタジオの値列挙は、すべて同じ式を読む。入力に対するあるべき値は
`tests/test_material_values.py`が期待値の表で固定する。

**タイルへ焼く式だけは符号化が違う**。`CASE WHEN 条件 THEN true END`で「該当しない」を
NULLへ畳み、フィーチャーからキーを省いてタイルを軽くする。材料の値を求める式は
タグが無ければ非該当（false）へ畳む（`tag_absent_is_false_sql`）——wayの行は必ずある
（`road_edges.osm_way_id`がNOT NULL + FK）。**違うのは符号化だけで、条件は同じ式**:
欠損を非該当として持つ真偽の材料（`material_array_group`が`"boolean"`の材料）のうち
`tile_property`を持つものは、タイルの列を`CASE WHEN (value_sql) THEN true END`として
カタログから組み立てる（`road_graph_repository.py: _BOOLEAN_TILE_COLUMNS_SQL`）。材料を
1つ足せばタイルにも列が増え、条件を直せば地図と評価が一緒に変わる（タイルの形の署名も変わり、
配信中のタイルは作り直しになる）。この形が成り立つのは値式が`w`だけを読むときで、タイルの
FROM句に`re`は無い。例外は`surface_good`で、`true`/`false`/NULLを区別する（「路面タグ不明」を
「路面が悪い」と混同しないという要求が符号化より優先された）ため、値式をそのまま焼く。

## 0次ハードフィルタ（`domain/hard_filters.py`）

`compute_hard_filter_excluded`が、材料の表から読んだフィルタ名→該当フラグの配列と、
リクエストが指定した有効なフィルタ名の集合から、Edgeごとの除外を求める。`hard_filters`
省略時は`DEFAULT_HARD_FILTERS`（宣言されている全フィルタが常時有効）を使う。

**受け取るフラグのキー集合は宣言と完全一致でなければ落ちる**——欠けたフィルタは黙って
無効になり、高速道路や`bicycle=no`の道がそのまま候補へ入る。リクエスト側の名前も宣言に
無いものは拒む（綴り間違いと「そのフィルタを切った」を区別できないため）。

- highwayタグ由来（`motorway`/`trunk`）・`bicycle=no`タグ（`no_bicycle`）の2系統。
  **除外の根拠は種類ごとに違う**: `motorway`（motorway/motorway_link）は法的に自転車が
  通行できない。`trunk`（trunk/trunk_link）は日本の法規上は通行可能な場合が多く、
  ロードバイクの周回ルートにとって実務上走りにくい・危険という**用途上の判断**で外して
  いる。trunkは地図表示（幹線道路の把握・回避判断）のために取り込みはする——取込
  スコープと探索スコープが食い違っているのは意図した役割分担である。
  highway種別のフィルタは`HARD_FILTER_HIGHWAY_TYPES`（フィルタ名→画面に出す名前と対象highway値）が唯一の
  レジストリで、`compute_hard_filter_excluded`はこの辞書をループする（`compute_hard_filter_excluded`が受け取るのはフィルタ名→該当フラグ配列の
  `hard_filter_flags`で、フィルタごとの専用引数・専用フィールドは持たない。タグ由来の
  フィルタは`HARD_FILTER_TAG_PREDICATE_SQL`が名前・画面に出す名前・判定式をまとめて持ち、
  `HARD_FILTER_NAMES`も読み出し用のSQLの列もそこから導く）。
  フィルタを1件増やしても変わるのはこの辞書だけ。
  highwayタグが無い・way_tagsが未取得の場合は除外しない（判断材料が無いEdgeまで一律
  除外すると探索対象が過度に狭まるため、不明な場合は許可しSoft Constraint側へ委ねる）。
- `max_average_grade_percent`（省略時None＝除外なし）が指定され、かつ
  `elevation_attribute.average_grade`が取得済みの場合、その絶対値（登り・下りどちらの
  急勾配も対象）がしきい値を超えるEdgeを除外する。
- `motor_vehicle=no`（自転車可の車両通行禁止）はここでは扱わない。自転車は法的に通行
  可能なため0次のハード除外対象にはせず、二次軸（車ストレス）側の補正として扱う。

軸単位の評価（[軸スタジオ](axis-studio.md)の`priority_overrides`、材料の値が一致すれば
評価を優先確定する仕組み）とは別の概念——0次フィルタは道路そのものを探索グラフから
除外する。

## 材料の求め方は1本（読む経路は粒度ごとに分かれる）

材料の値の求め方は`MaterialSpec.value_sql`だけが知っている。読む経路は粒度ごとに分かれるが、
**どの経路も材料の一覧を持たず、式も持たない**——DBが値を返し、受け取る側は列を並べるだけ。

| 経路 | 入口 | 粒度 |
|---|---|---|
| 区間の評価 | `road_graph_repository.py: get_edge_material_arrays` | 区間群（タイル1枚ぶん） |
| way1本 | `road_graph_repository.py: get_way_material_values` | way1本（区間インスペクタ） |
| way標本 | `road_graph_repository.py: sample_way_material_values` | way標本（軸スタジオの分布プレビュー） |

way粒度の経路も**区間向けと同じ式**を使う。`_way_from_clause`がwayの行から同じ名前の
エイリアス（`_WAY_ALIAS_CLAUSES`が持つ`wm`/`re`/`em`）を組み立てるだけで、式を2組持たない。
区間の値を持つ`em`は、way粒度では`way_materials`を引く別名になる——**区間の値をway1本へ
落としているのではなく、way粒度の値を同じ名前で読んでいる**（way側の値は
`derive_raster_materials`が区間から集約して持つ）。

**暗黙の前提**: 取込はタグを絞らない（`batch/source_adapters/osm_pbf.py`がタグを全部`attrs`へ入れる）。どのキーも
`attrs`に在るため、値式はそこから読んでよい。**捨てると後から解釈を変えられない**という
理由で全部持つ設計で、許可リストは持たない。

**この1本道が壊れたときに起きること**: 経路ごとに式を書くと、片方だけ変更されたときに
同じ道の同じ場所で地図の色と採点・内訳の数字が食い違う。合成コストは他の軸でも決まるため、
食い違ってもルートは返り続け、誰も気づかない。

## 材料の解決から合成コストまで（3段階）

```
一次: 材料の値（DBが`MaterialSpec.value_sql`で導出、`EdgeMaterialArrays`）
        │  動的材料（風）だけはリクエスト時に`evaluate_dynamic_material_arrays`が
        │  bearing配列・天候・走行速度から求める
        ▼
  二次: 軸id → difficulty(0-100) の辞書
        │  domain/axis_definitions.py: evaluate_axes_scalar が AXIS_DEFINITIONS を評価
        │  （軸が他の軸のdifficultyをmaterialとして参照する階層構造も含む）
        ▼
  三次: compose_costs_from_axis_matrix(distance_m, axis_arrays, weights, penalty_strength)
        │  cost = 下地 × (1 + P × Σᵢ wᵢ × axisᵢ / 100)
        ▼
  cost・difficulty配列（0次フィルタの除外は`compute_hard_filter_excluded`が別途判定）
```

way1本を指す区間インスペクタだけはスカラーで評価する（`axis_inspector_breakdown`→
`evaluate_axes_scalar`）。

- 評価できなかった軸は合成から除外され、残りの重みで再正規化される。
- `penalty_strength`（P）は**主観的割増と時間の換算レート**。リクエストが省略したときの値は
  較正値`evaluation.penalty_strength`（`domain/tuning.py`）だけが持ち、`resolve_penalty_strength`が
  リクエスト処理時に読む（`compose_costs_from_axis_matrix`は既定を持たない）。探索のコストは
  `所要時間 × (1 + P × difficulty/100)`＝体感の所要時間で、P=1は「難易度100の道は
  体感で2倍の時間」を意味する。P=0で`cost=下地`（好みを一切考慮しない＝時間最短、
  `select_fastest_route`が返す基準線と同じ物差し）、Pを上げるほど悪路が強く避けられる。
  `cost >= 下地`という不変条件はP>=0の間常に成り立つ（下地は探索では区間ごとの
  所要時間、Edge単位の評価では距離）。
- **`_evaluate_axes_from_material_arrays`**: `AXIS_DEFINITIONS`を軸ごとに適用して
  difficulty配列を求める（`BulkAxisEvaluation`: 公開軸別配列に加え、0次フィルタ判定用の
  生フラグ`hard_filter_flags`/`gradient_percent`も返す——`hard_filters`はリクエストごとに
  変わりうるため、除外判定そのものはここでは確定させない）。動的材料
  （`REQUEST_DYNAMIC_MATERIAL_IDS`、風）の列はNaNのままで、それに依存する軸の列も自然に
  NaNへ伝播する（動的軸の特別扱いが不要）。
- **`compose_costs_from_axis_matrix`**: 軸別スコア配列群と重み辞書からNeumaier加算→
  `round1_array`丸め→cost算出まで配列演算で行う。0次フィルタによる除外
  （`compute_hard_filter_excluded`が`hard_filters`/`max_average_grade_percent`を反映して
  別途判定）はここには含まれない。重み付き軸がすべて欠損のEdgeはcost算出だけbbox内平均
  difficultyを代入する（表示用の戻り値には影響しない、詳細は後述「探索コストの既定経路」節）。

**暗黙の前提（浮動小数点の一致）**: `_neumaier_accumulate`（Neumaier補償加算のnumpy版）は
Python組み込み`sum()`（Python 3.12以降、Neumaier補償加算を使う）とビット単位で同じ
結果を返すために存在する。単純な逐次`+=`ではちょうど.X5境界の値で最終丸め結果が
スカラー経路（`composite_difficulty`）と食い違う。最終丸めも同じ理由で`round(x, 1)`と
ビット単位で一致させる必要がある（`round1_array`）。`×10→np.rint→÷10`を配列全体で
まとめて計算し、計算後の値がちょうど`.5`に乗った要素だけ、その要素の元の値へPythonの
`round()`（10進の正しい丸め）を個別に適用して結果を決め直す。軸1本の得点
（`evaluate_axis_array`）も同じ`round1_array`で丸める。

**暗黙の前提**: 軸が読む材料の配列は`MATERIAL_CATALOG`の全材料ぶん確保する
（`value_sql`を持たない材料も既定値[NaN/False]で確保）。確保しないと、値式が無い材料を
軸スタジオでGUI作成した軸を評価した際に`evaluate_axis_array`が`KeyError`で
`/api/routes/generate`自体を落とす（スカラー版`evaluate_axes_scalar`は
`materials.get(...)`のためこの経路では発生しない非対称性がある）。

## 探索範囲の静的スコア行列と動的軸合成（探索コストの既定経路）

`RoadGraphEngine`（[routing-engine.md](routing-engine.md)参照）が実際に使う探索コスト
算出の既定経路。探索中にEdge1本ごとにPythonのコスト計算コールバックを呼ぶ構造を避け、
bbox全体ぶんのコストをリクエストにつき1回だけnumpyで合成することで、A*本体へは配列への
`list.__getitem__`だけを渡す。

- **`build_static_edge_score_matrix`**: 生成のたびに、切り出した探索範囲の材料
  （`GraphService.get_search_slice`）から`StaticEdgeScoreMatrix`（Edge×公開軸の静的スコア行列＋distance_m・
  bearing_deg・0次フィルタ判定用の生配列、行は切り出した区間の順）を構築する。キャッシュしない——
  軸定義の編集がそのまま次の生成に効く。
- **`DynamicAxisRequestContext`/`DYNAMIC_MATERIAL_EVALUATORS`/
  `evaluate_dynamic_material_arrays`/`evaluate_dynamic_axis_arrays`**: リクエスト時点で
  風などの動的材料（`REQUEST_DYNAMIC_MATERIAL_IDS`）を実際の値へ差し替える。
  `DYNAMIC_MATERIAL_EVALUATORS`は材料id→evaluator関数（Edgeの幾何配列＋動的contextを
  受け取りその材料の配列を返す統一シグネチャ）の登録制ディスパッチで、
  `REQUEST_DYNAMIC_MATERIAL_IDS`と1対1に揃える（現状は`wind_drag_ratio`の1件。式の実体は
  `domain/wind.py`にあり、ここは配線のみ）——
  `REQUEST_DYNAMIC_MATERIAL_IDS`自体が材料id集合として宣言されているため軸id単位では
  なく材料id単位で登録する（`dynamic_axis_topological_order`・`evaluate_axis_array`
  という既存の汎用トポロジカル合成が「動的材料さえ埋まればどんな軸[軸スタジオが
  動的材料を直接参照して作ったカスタム軸を含む]でも正しく合成する」ため、
  軸名のハードコードは呼び出し側に一切現れない）。動的材料が増えたら
  `REQUEST_DYNAMIC_MATERIAL_IDS`とこの辞書へ1エントリずつ追加するだけでよい（CLAUDE.md
  原則1、フロントがramp軸をカタログ［`axisCatalog.rampAxes`］から列挙して塗るのと同種の汎用ディスパッチ）。
  `evaluate_dynamic_material_arrays`が全動的材料を評価する唯一の経路で、静的行列への
  動的軸合成（`evaluate_dynamic_axis_arrays`）もここを通るため、式が乖離しない。
  `DynamicAxisRequestContext`は出発時点のスナップショット（`weather`）・走行速度
  （`travel_speed_ms`、m/s。既定値を持たない必須フィールドで、伝播漏れは構築時点で
  失敗する）に加え、時刻依存の材料向けに時別予報（`wind_series`、格子点ごと）・出発時刻
  （`start`）・Edgeごとの通過予定時刻（`passage_hours`）と最寄りの格子点（`wind_points`。どちらも
  `bearing_deg`と同じ行順）を持つ。
  3つが揃えば風の材料はEdgeごとにその時刻の風で求め（`wind_inputs()`）、揃わなければ
  スナップショットを全Edgeへ一様に使う。`StaticEdgeScoreMatrix`は通過予定時刻の推定に
  使うEdge中点座標（`mid_lat`/`mid_lon`、from/toノードの平均）も持つ（タイル単位で
  キャッシュ）。
- リクエスト時（`RoadGraphEngine._build_search_graph`）は、`StaticEdgeScoreMatrix`を
  軸id→配列の辞書へ展開→`evaluate_dynamic_axis_arrays`で動的軸を上書き→
  `compose_costs_from_axis_matrix`で重み合成→`compute_hard_filter_excluded`で0次
  フィルタを適用、の順にbbox全体ぶん1回だけ実行してコスト配列を得る。並行Edge
  （同一Node間の複数Edge）は`domain/routing.py: build_lazy_road_graph`がedge_idの昇順で
  先頭を採用する決定的な規則で解消する（コストは見ない。`LazyRoadGraph`はコストに
  依存せずタイル集合キーでキャッシュするため）。
  同じコスト配列・軸別スコア配列は`_build_segment_details`（区間表示）からも参照され、
  探索と表示の二重計算を避ける。区間の軸別寄与度（表示用）は`axis_contributions_at_row`が
  経路上の区間ぶんだけ、合成が返した重みの和（`AxisComposition.weight_sums`）を分母に求める
  ——全区間ぶんは作らない。**唯一の例外**（探索コストのみ補完・表示は変えない、
  `docs/architecture/design-principles.md`「探索コストと表示difficultyの一致」参照）: 重み付き軸が
  すべて欠損（composite=NaN）のEdgeは、探索コスト算出にだけbbox内の距離加重平均
  difficultyを代入する（`compose_costs_from_axis_matrix`が内部で
  `distance_weighted_difficulty_array`により算出、`RouteSegmentDetail`側のdifficulty・
  axis_difficultiesはNaN=Noneのまま変わらない）。`_build_search_graph`のINFOサマリ
  （`missing_axis_edges`/`missing_axis_distance_ratio`）でリクエストごとの発生比率を
  観測できる。

## ルート単位の集約（`domain/difficulty.py`）

区間ごとのdifficultyをルート1本の値へまとめる2つの指標を持つ。どちらも
`route_generator.py: SEGMENT_AGGREGATES`の宣言を`_evaluate_and_aggregate`が同じsegmentsへ同時に当てて付ける。

| 指標 | 定義 | 性質 |
|---|---|---|
| `overall_difficulty` | 距離加重平均（`distance_weighted_difficulty`） | 距離で正規化されるため、遠回りして難所を避けるほど下がる。候補の並び順はこの昇順 |
| `difficulty_load` | 平均×距離合計（`difficulty_load`） | 距離が伸びればそのまま増える。「走り切るまでのしんどさ」に近く、遠回りが不利に出る |

同じ集約を軸の**生値**（折れ点を通す前の値、`BulkAxisEvaluation.axis_raw_arrays`）にも
掛ける（`RouteSegmentDetail.axis_raw_values`→`merge_axis_raw_values`→
`RouteCandidate.axis_raw_values`）。得点0-100は目盛りの引き方に依存する相対評価のため、
軸単体で経路を判断するには絶対値が要る。生値を持つのは単位が定まる軸
（[軸スタジオ](axis-studio.md)「生値の単位」節）だけで、かつリクエストごとに変わる
材料（風等）を参照する軸は静的スコア行列へ載らないため対象外。

**単位が定まらない軸は、代わりに材料まで分解した絶対量を持つ。** 分解は
`axis_raw_value.py: axis_material_shares`が軸定義から機械的に行い、軸参照
（車の圧迫感の内部軸5本）は葉の材料まで再帰的に辿る——途中の軸の得点は内訳に含めない。
得点を内訳へ混ぜると、この仕組みが解こうとしている「較正依存の数字しか出せない」問題が
入れ子で再発するため。並び順は各階層で`|w| / Σ|w|`へ正規化した重みの積の降順
（生の重みは階層をまたぐと比較できない——内部軸の`breakpoints`・`mapping`が非線形変換の
ため。一方、同じshape内のtermどうしは、重み付き和が得点として意味を持つよう作者が
重みを決めていることが前提なので比較できる）。重み0の材料は含めない。

参照材料が1件へ分解される軸は分解せず、軸単位の生値をそのまま使う（`axis_material_shares`
が空リストを返す）。分解しても情報が増えず、`shape.preprocess`（勾配の`"abs"`）が材料単位
では効かなくなり、登りと下りが相殺されて平均がほぼ0になるため。

値の運搬は生値と同じ形で、静的スコア行列の材料列
（`StaticEdgeScoreMatrix.material_ids`/`material_values`、列を決める述語は
`route_facing_material_ids`が唯一の定義元）→`RouteSegmentDetail.material_values`→
`merge_material_values`→`RouteCandidate.material_values`。真偽値材料は0/1のfloatで持つため、
距離加重平均がそのまま「該当区間の延長割合」になり、割合専用の機構を持たずに済む。
categorical材料は数値列に載せられないため、対になる別の列で運ぶ:
`StaticEdgeScoreMatrix.categorical_material_ids`/`categorical_material_values`
（文字列のobject配列、列を決める述語は`route_facing_categorical_material_ids`）→
区間ごとの値（`road_graph_engine.py: _build_segment_details`が区間の並びと対で返す。
区間の器`RouteSegmentDetail`は約500mのビンへ畳まれ、分類値はビンの代表値1つにすると
割合がビンの粒度へ量子化されるため、器には載せない）→
`merge_material_category_shares`（距離加重で「値ごとの延長割合」へ畳む。分母はその材料の値を
持つ区間だけで、値の無い区間は分母にも入れない）→`RouteCandidate.material_category_shares`。
真偽値材料を0/1で運んで平均が割合になるのと同じ考え方を、値が3つ以上ある材料へ広げたもの。

**丸めは値の種類で分ける**。距離加重平均そのものは`weighted_mean_by_distance`
（`domain/difficulty.py`、丸めない）が求め、丸め方は呼び出し側が決める——
difficulty系（0〜100）は小数1桁、生値・材料値は**有効数字4桁**。
生値のスケールは軸ごとに違い（勾配は`%`で0〜15程度、事故密度は`件/(km・年)`で
有効域0〜0.5）、固定の小数桁で丸めると桁の小さい軸で値がまるごと潰れて
「値が無い道」と区別できなくなる。frontendの表示（`axisRawValue.ts: formatNumber`）も
同じ理由で1未満は有効数字2桁を残す。

`difficulty_load`は順位付けには使わず、平均と併せて判断材料として返す。difficultyが
Noneの区間の扱いは平均と一致させる（区間ごとに積分して欠損を飛ばすと、データの無い区間が
多いルートほど総量が小さく見えてしまうため、平均×全区間の距離合計で求める）。

## 材料カタログ（`domain/material_catalog.py`）

評価軸が参照する材料（material）の正式カタログ。`MATERIAL_CATALOG: dict[str,
MaterialSpec]`が単一ソース。

`MaterialSpec`の主なフィールド:

| フィールド | 意味 |
|---|---|
| `dtype` | `"numeric"`/`"boolean"`/`"categorical"` |
| `unit` | 値の単位（凡例・比較パネル等の数値表示用、無次元・真偽値・カテゴリ値は空文字）。`GET /api/material-catalog`が配信し、frontendは単位を持たない（唯一の正）。**`label`へ単位を書かない**——ラベルと単位を別々に組み立てる画面で「制限速度(km/h) 35km/h」のように二重になる |
| `additive` | 同じ単位の他の材料と**足し合わせて意味を持つ量**か（示量／示強の区別）。個数と、それを同じ距離で割った密度はTrue。%・km/h・倍率のような割合・率はFalse。`raw_value_unit`が2項以上の和を見せてよいかの判定に使う |
| `total_unit` | 生値へ走行距離を掛けた**総量**を出すときの単位（出す意味が無ければ`None`）。`additive`とは別の問い——事故密度（件/[km・年]）は足せるが、総量に比べる尺度が無い。|
| `tile_property` | MVTタイルへ既に焼き込み済みのプロパティ名。`None`は「タイル非依存」（地図レイヤーのramp自動生成の対象になりえない） |
| `tile_property_needs_runtime_scale` | タイル側の生値と材料の値がスケール不一致（実行時に変動する係数での変換が必要）か。地図表示の自動導出はこれがTrueの材料を含む軸を拒否する |
| `tile_property_direction_dependent` | 値が進行方向によって変わる（有向）か。地図のrampレイヤーは単色の線という前提のため、これがTrueの材料を含む軸もramp自動導出を拒否する |
| `primary_attribute` | 対応する一次属性（`PRIMARY_ATTRIBUTES`の宣言そのもの。idの文字列では指さない。[軸スタジオ](axis-studio.md)「一次属性レジストリ」節）。材料idと一次属性id（frontendの`primaryAttributes.ts`が使う名前空間）は名前が異なるため明示的に対応させる |
| `value_sql` | その材料の値をDBから求めるSQL式。`None`は「SQLでは求められない」（リクエスト時に決まる風、評価へ配線していないトリガー付きDEFER） |
| `coverage` | 欠損率の測り方。way単位・区間単位・対象外の3択で、**どれかを必ず持つ**（どちらの一覧にも載っていない材料を型として作れなくする） |
| `bool_default` | `dtype="boolean"`の材料が欠損を取りうるときの配列上の扱い。`"false"`（真偽の行列へ載せる）か`"nan"`（不明を非該当と混同しないため数値の行列へ載せる）で、数値的に等価ではない。**宣言ではなく`coverage.missing_semantics`から導くプロパティ**（`"unknown"`なら`"nan"`）——欠損の意味を2か所に宣言すると、片方だけ書き換えたときに画面と評価が食い違う |
| `value_labels` | categorical材料の値ごとの日本語ラベル対訳表（`GET /api/admin/material-catalog/{id}/values`が返す） |
| `reference_points` | 軸スタジオの折れ点編集を助ける「値の目安」一覧（`MaterialReferencePoint`のlabel/value）。値域が直感的でない材料（風等）ほど有用で、真偽値・categorical材料や単純な材料は空リストのままでよい。換算式はbackendだけが持ち、値はここで計算済みのものを持たせる |

- **評価軸が参照する材料は、正規化された生データ（数値・boolean・単純categorical）に
  統一する。** 地図表示・API応答向けの人間可読な分類ラベル（「この道は自転車レーンあり」
  のような優先順位付きの多値分類）は別レイヤーの関心事で、材料にしない——分類の順位付けが
  評価の重み付けと二重になり、片方だけ変えたときに気づけない。逆に、評価軸から参照され
  なくなったという理由**だけ**では表示側の分類を消さない（別の独立した消費者が実在する
  限りは残す）。
- 材料の「登録」（本カタログに載る）と「評価軸での利用」（`AxisDefinition.shape`が
  実際に参照する）は独立している。登録済みでも対応する軸が無ければ評価には使われない
  （軸スタジオの材料選択肢には現れる）。
- 材料自体はGUIから追加・編集・削除できない（コード変更＋デプロイが前提）。軸スタジオ
  は`GET /api/material-catalog`経由で本カタログを動的取得する。
- 風の材料は`wind_drag_ratio`（無次元。相対風速ベクトルの二乗則で求めた、時速20kmで無風の
  ときの空気抵抗を1とする進行方向の抵抗増分。`domain/wind.py: wind_drag_ratio_array`、
  基準速度`WIND_DRAG_REFERENCE_SPEED_MS`は`ASSUMED_SPEED_KMH`とは独立の定数）。
- 土地被覆の割合材料は`edge_materials.lc_*`／`way_materials.lc_*`（区間単位・way単位、
  [静的道路属性・タイル配信](static-road-attributes.md)）が持つクラス別の割合で、
  **どのクラスが割合列を持つかは`landcover.py: LANDCOVER_CLASSES`が単一の正本**で、
  列指向テーブル・集計SQL・読み出し・タイルの焼き込み列は、そこからクラス値の昇順で
  導いた`PERCENT_CLASSES`を読む（材料そのものの宣言は`material_catalog.py`が別に持つ）。
  **区間単位の行があればそちら、無ければway単位へ落とす**。
  区間の行が「計算済み・値なし」のときもway単位へは戻さない——行の有無で決める。
  この切り替えは路面タイル・区間インスペクタ（`get_feature_landcover`）と同じ規則で、
  **揃えないと同じ道の同じ場所で地図の色と採点・内訳の数字が食い違う**。
  値式は区間単位の列（`el`）とway単位の列（`wl`）を`COALESCE`で繋いでこの規則を表す。

  **欠損判定に1クラスを名指ししない。** 判定も読み出し列もクラスの宣言から導く
  ——名指しすると、クラスを1つ足して既存行を埋め戻す前に、その列がNULLというだけで
  行ごと捨てる。
  **1つの軸で複数のクラスを足さないこと**——割合の合計が100%へ固定されているため
  同じ地面を二重に数える（[設計原則](../../architecture/design-principles.md)構造仕様14）。
- 値式は`domain/material_sql.py`の組み立て関数から作る（タグの正規化・タグ値の一致・
  数値パース・件数の密度化・wayの行の有無）。同じ判定を材料ごとに書き写さないため、
  判定を直すと全材料へ同時に効く。

### 値式が参照するエイリアス

値式は**材料の数が増えてもエイリアスが増えない**形で設計する。元データの出どころごとに
1つのエイリアスを用意し、材料はそのどれかの列を指す。

| エイリアス | 元データ | ここから生える材料 |
|---|---|---|
| `w` | 生の道（`source_features`の`source='osm_way'`を、よく引くタグを列へ出した副問い合わせ。`material_sql.py: ways_source_sql`） | `surface`・`lit`・`maxspeed_kmh`・`bridge`・`smoothness`等 |
| `re` | 区間の行（`road_edges`） | `highway`・距離（密度の分母） |
| `em` | 区間に付く値（`edge_materials`） | 標高・件数の密度・区間単位の土地被覆 |
| `wm` | 道1本に付く値（`way_materials`） | way単位の土地被覆・道の曲がり具合等 |

way粒度で引くときは、同じ式のまま`w`の行から同じ名前の別名を組み立てる
（`road_graph_repository.py: _way_from_clause`）。`em`はway側の同名列かNULLを返す1行になる
ため、区間にしか無い値（標高）はNULLになる。

**行の有無と値の有無を分ける。** `w`の行が無い（未取込の地域・PBF再取込の途中）ときは
タグ由来の材料がすべて不明（NULL）になり、行があればタグが無くても非該当（false）として
確定する（`tag_absent_is_false_sql`）。件数も同じで、集計行が無ければ不明、行があれば
載っていないキーは0件。集計前を0件として読むと、全区間が「停止要因ゼロ＝最も易しい」と
評価されてルート選択が静かに歪む。

`MaterialDType`（`numeric`/`boolean`/`categorical`）は、元データの出どころを
増やしても増えない。

**エイリアスを足してよいかの判定基準**: その材料の兄弟が今後増えるなら、既存の
エイリアスの列として足す。新しいエイリアスを足すのは、元データの表そのものが増えるとき
だけ（`_way_from_clause`・区間向けのFROM句の両方へ同じ名前で用意する必要がある）。

### 材料カタログのAPI（`api/routers/material_catalog.py`）

| エンドポイント | 認可 | 内容 |
|---|---|---|
| `GET /api/material-catalog` | 不要 | `display_only=False`の材料一覧（`material_id`/`label`[論理名 - 物理名]/`description`/`dtype`/`unit`/`reference_points`のみ。`tile_property`等のbackend内部フィールドは含めない） |
| `GET /api/admin/material-catalog/{material_id}/values` | HTTP Basic | categorical材料の実データ値一覧（`RegionService.get_material_values`経由、未知idは404・値一覧を持たない材料は空リスト・DB未接続や障害は`available=false`）。索引の効かない`SELECT DISTINCT`をタイル配信と同じ接続プール上で実行するため、`coverage`と同じく認可を課す |
| `GET /api/admin/material-catalog/coverage` | Basic認証必須 | 材料ごとの欠損割合（下記）。全表走査を伴うため認可なしには公開しない |

## 材料の欠損割合（`infrastructure/material_coverage.py`・`services/material_coverage_service.py`）

欠損データを取込側で推測して埋めるのではなく、欠損の実態を管理画面
（[軸スタジオ管理画面（frontend）](../frontend/axis-studio.md)「材料」タブ）で可視化し、
埋めるかどうかの判断は軸定義側へ委ねる。「欠損」は元データ（OSMタグ・派生テーブルの行）の
不在を指し、評価パイプラインが不在をどう扱うかは`missing_semantics`として併記する。

材料id→「どの母集団の、どの条件が成り立てば欠損か」は各材料の`MaterialSpec.coverage`が宣言し、
`material_coverage_specs()`がカタログから集めて`MATERIAL_COVERAGE_SPECS`（導いた値で、宣言ではない）にする。

| 母集団 | 対象 | 判定 |
|---|---|---|
| `"way"` | 生の道の全行（`WAYS_SOURCE_SQL`） | `missing_condition`（生の道の列・`tags` JSONBのみで構成したSQL真偽式、`domain/material_sql.py`の共有断片から組み立てる）。全way材料を`count(*) FILTER`で1回の走査にまとめる（`build_way_coverage_sql`、`FROM {WAYS_SOURCE_SQL} AS w`）。判定式は[routing-engine.md](routing-engine.md)の`_ROAD_SURFACE_TILE_MVT_SQL`と同じPython定数を参照するため、独立した2つの文字列を突き合わせる形の整合性テストは持たない（同じ定数を使う構成自体が一致を保証する） |
| `"edge"` | `road_edges`全行 | `present_condition`（`edge_materials AS em`の1行が値を持つときに真のSQL条件式）。全edge材料を`count(*) FILTER`で1回の走査にまとめる（`build_edge_coverage_sql`）。`edge_materials`の`(osm_way_id, segment_index)`は`road_edges`へのFK（ON DELETE CASCADE）のため、値が埋まっている行数をそのまま「値ありEdge数」として使いJOINを省く |

- **「行がある」と「値がある」を混同しない**。派生テーブルが「行が無い＝未計算」と
  「列がNULL＝算出不能」を区別するなら（土地被覆の`lc_*`がそう）、行の有無だけで数えると
  値がNULLの行を「データあり」と数えてしまう。判定は評価が実際に読む**列**のNULLまで見る。
- `missing_semantics`: `"unknown"`（欠損は不明値[NaN/None]として扱われ、その材料を使う軸は
  評価対象外になる）／`"definite"`（欠損は確定値[タグ不在=非該当等]として扱われ、軸は
  通常どおり評価される）。真偽の材料の配列上の欠損の持ち方（`MaterialSpec.bool_default`）は
  これから導く——`"unknown"`の材料は欠損を`NaN`で持ち、非該当（`false`）と混同しない。
- `CoverageExcluded(reason=...)`: 集計対象外の材料とその理由（動的計算材料の
  `wind_drag_ratio`、NOT NULL列由来の`oneway`等）。
  管理画面はこの理由をそのまま表示する。
- **どちらか一方を必ず持つことは型が保証する**: `MaterialSpec.coverage`は必須で、
  way単位・Edge単位・対象外の3択（`MaterialCoverage`）のいずれかしか取れない。
  「どちらの一覧にも載っていない材料」を作れないため、網羅性を確かめるテストは要らない。
- `MaterialCoverageService.get_material_coverage`はDB例外を握りつぶさず伝播させ、router側で
  503へ変換する（診断用APIのため空レポートへ倒して「欠損0件」に見せない）。
  `api/dependencies.py: get_material_coverage_service`はルート生成用の長い
  `command_timeout`（180秒）を持つセッションを渡す（全表走査がタイル配信用の20秒を
  超えうるため）。
- 欠損の扱いと母集団の画面の名前（管理画面の欠損率の見出し・説明）は、同じファイルの`MISSING_SEMANTICS_DISPLAY`・`POPULATION_LABELS`が持ち、生成物`vocabulary.ts`で画面へ届く。

## 区間インスペクタ（`axis_inspector_breakdown`）

単独でクリックされたway（ルート文脈が無い）について、「一次属性→二次軸→三次合成コスト」を
算出する。材料値は`RoadGraphRepository.get_way_material_values`が返したものをそのまま受け
取り、この関数は合成だけを行う。進行方向に依存する材料（勾配%・風ペナルティ）は
**1本の道が往復2方向で違う値を持つ**ためDBのway単位の値には無く、走行方位・時刻・想定速度を
指定して呼び出し側（`api/dependencies.py: directional_materials`）が引いたものを
`materials`へ足して渡す。足されなければその軸は`available=False`になる。
`covered_weight_fraction`（全軸の
重み合計に対する取得できた軸の重み合計の割合）をフロントの「参考値」表示に使う。


## RoutePreference（`domain/route_preference.py`）

`weights: dict[str, float]`（axis_id→重み、既定値は`default_axis_weights()`）。
バリデーションは公開軸（`is_published=True`）のキー集合の完全一致を要求する（内部軸は
一般ユーザー・リクエストからの重み付け対象外）。

- `with_weight(axis_id, value)`: 1軸の重みだけを差し替えたコピーを返す。`axis_id`が
  現在の`weights`（＝現在の公開軸集合）に無い場合は無変更の`self`を返す。
- `with_time_scope(active_scopes)`: `time_scope`が`"always"`以外の軸のうち
  `active_scopes`に含まれないものの重みを0倍にしたコピーを返す（night軸の動的重み
  付けが使う、[routing-engine.md](routing-engine.md)参照）。

いずれもリクエスト間で共有するインスタンスを汚染しない生成ヘルパーとして、新しい
`RoutePreference`インスタンスを返す（`self`を書き換えない）。

## 評価のオーケストレーション（`services/evaluation_service.py`）

`load_route_preference()`が既定の`RoutePreference`（`RoutePreference()`、
`default_axis_weights()`由来）を返す。このモジュールが持つのはそれだけで、評価そのものは
domainが行う。状態を持たないためクラスではなくモジュール関数。
