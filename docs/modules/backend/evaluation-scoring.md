# 評価・スコアリング（backend）

## 責務

道路のEdge/区間から、0次フィルタ判定・軸別difficulty・合成difficulty・探索用cost・
候補集合内の相対スコアを算出する。軸ごとの評価式自体（`AxisDefinition.shape`の評価）は
[軸スタジオ・評価軸定義](axis-studio.md)が持ち、本モジュールはその1段上（材料の解決・
複数軸の合成・0次フィルタ）を担う。

**対象ファイル**

| レイヤー | ファイル |
|---|---|
| domain | `evaluation.py`・`difficulty.py`・`material_catalog.py`・`recipe.py` |
| services | `evaluation_service.py`・`material_coverage_service.py` |
| infrastructure | `material_coverage.py`（材料ごとの欠損割合の集計クエリ） |
| api | `material_catalog.py`（材料カタログ・材料値一覧・欠損割合のエンドポイント） |

`infrastructure/osm_way_tag_sql.py`（`osm_raw_ways`のOSMタグ分類SQL断片の単一の情報源、
[routing-engine.md](routing-engine.md)の`_ROAD_SURFACE_TILE_MVT_SQL`と本モジュールの
`material_coverage.py`が共有する）は[routing-engine.md](routing-engine.md)が主管するため
対象表には加えず参照のみ行う。

## 0次ハードフィルタ（`domain/evaluation.py`）

`DEFAULT_HARD_FILTERS: frozenset[str] = frozenset({"no_bicycle", "motorway", "trunk"})`。
`is_edge_allowed(edge, hard_filters=None)`が、`hard_filters`省略時はこの既定集合（全
フィルタ常時有効）でEdgeを探索グラフに含めるか判定する。`RoutePreference`が個別ON/OFF
上書きを持つ（`evaluation_service.py`が既定Noneを受け取り解決）。

- highwayタグ由来（`motorway`/`trunk`）・`bicycle=no`タグ（`no_bicycle`）の2系統。
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

## 材料の解決から合成コストまで（3段階）

```
一次: Edge/way_tags/elevation_attribute等の生データ
        │  compute_edge_axis_scores(edge, elevation_attribute, surface_type, weather, ..., travel_speed_ms)
        │  MATERIAL_CATALOGの各extractorが材料値（材料id→スカラー値）を組み立て、
        │  動的材料（風）はcompute_dynamic_edge_materialsが風・走行速度から求める
        ▼
  二次: 軸id → difficulty(0-100) の辞書
        │  domain/axis_definitions.py: evaluate_axes_scalar が AXIS_DEFINITIONS を評価
        │  （軸が他の軸のdifficultyをmaterialとして参照する階層構造も含む）
        ▼
  三次: compute_cost_from_axis_scores(distance_m, axis_scores, weights, penalty_strength)
        │  cost = length × (1 + P × Σᵢ wᵢ × axisᵢ / 100)
        ▼
  EdgeCostResult（cost・difficulty・allowed）
```

`compute_edge_cost`はこの3段を一気通貫でまとめる薄い合成関数。三次のみを直接使いたい
場合（レジストリ・Recipe駆動の呼び出し）は`compute_cost_from_axis_scores`を直接使う。

- 評価できなかった軸（Noneのdifficulty）はキー自体を辞書へ含めない
  （`compute_cost_from_axis_scores`は「データ無しは合成から除外し残りの重みで再正規化」）。
- `weights`省略時は`preference.weights`を使う。
- `penalty_strength`（P、既定1.0）は割増率の強さを調整するリクエストパラメータ。
  P=0で`cost=distance_m`（難易度を一切考慮しない最短距離探索）、Pを上げるほど悪路が
  強く避けられる。`cost >= distance_m`という不変条件はP>=0の間常に成り立つ。
- `bbox_mean_difficulty`（既定None）は、重み付き軸がすべて欠損（`difficulty is None`）の
  ときにコスト計算だけへ代入する値。戻り値の`difficulty`（表示用）はこの代入の影響を
  受けずNoneのまま。呼び出し元がbboxの実データから求めた値を渡す想定で、この関数自身は
  固定値を持たない（後述「探索コストの既定経路」節参照）。

## `compute_edge_costs_bulk`（numpyベクトル化版）

`compute_edge_cost`を全Edge分ループするのと同じ結果を、Pythonループ無しのnumpy配列演算で
算出する。抽出・計算フェーズ（`_evaluate_axes_bulk`）と重み付き合成フェーズ
（`compose_costs_from_axis_matrix`）に分かれており、道路グラフ探索のホットパス
（`build_static_edge_score_matrix`、次節）と共有する構造になっている。`EvaluationService.
evaluate_graph`（bbox全体を一括評価する経路）自体は本番のルート生成では呼ばれず
（探索コストの既定経路は次節）、回帰テストオラクルとしての利用が主。

- **`_evaluate_axes_bulk`（抽出＋計算フェーズ、Pythonループ1回＋配列演算）**:
  `MATERIAL_CATALOG`の`extractor`宣言を使いEdge単位の辞書・タグアクセスをnumpy配列へ
  落とし込み、`AXIS_DEFINITIONS`を軸ごとに適用してdifficulty配列を求める
  （`BulkAxisEvaluation`: 公開軸別配列に加え、0次フィルタ判定用の生フラグ
  `is_motorway`/`is_trunk`/`no_bicycle`/`gradient_percent`も返す——`hard_filters`は
  リクエストごとに変わりうるため、除外判定そのものはこの関数では確定させない）。
  動的材料（`REQUEST_DYNAMIC_MATERIAL_IDS`、風）は抽出ループを通らず、
  `evaluate_dynamic_material_arrays`（後述）がbearing配列・`weather`・`travel_speed_ms`から
  ベクトル計算する（`weather`を渡すときは`travel_speed_ms`が必須で、無ければ`ValueError`）。
  `weather=None`で呼ぶと動的材料がNaN配列になり、それに依存する軸の列は自然にNaNへ
  伝播する（動的軸の特別扱いが不要）。静的な材料を1件追加する際は`material_catalog.py`へ
  抽出関数を登録するだけでよく、この関数自体の変更は不要。
- **`compose_costs_from_axis_matrix`（重み付き合成フェーズ）**: 軸別スコア配列群と
  重み辞書からNeumaier加算→`round1_array`丸め→cost算出まで配列演算で行う。
  0次フィルタによる除外（`compute_hard_filter_excluded`が`hard_filters`/
  `max_average_grade_percent`を反映して別途判定）はここには含まれない。重み付き軸が
  すべて欠損のEdgeはcost算出だけbbox内平均difficultyを代入する（表示用の戻り値には
  影響しない、詳細は後述「探索コストの既定経路」節参照）。
- スカラー経路（`compute_edge_axis_scores`）と同じ軸定義データを読むため、軸の追加は
  定義データの追加だけで両経路へ同時に反映される。スカラー版`compute_edge_cost`は
  削除せず、本関数との出力一致を検証する回帰テストのオラクルとして残る。

**暗黙の前提（浮動小数点の一致）**: `_neumaier_accumulate`（Neumaier補償加算のnumpy版）は
Python組み込み`sum()`（Python 3.12以降、Neumaier補償加算を使う）とビット単位で同じ
結果を返すために存在する。単純な逐次`+=`ではちょうど.X5境界の値で最終丸め結果が
`compute_edge_cost`（スカラー版）と食い違う。最終丸めも同じ理由で`compute_edge_cost`の
`round(x, 1)`とビット単位で一致させる必要がある（`round1_array`）。`×10→np.rint→÷10`を
配列全体でまとめて計算し、計算後の値がちょうど`.5`に乗った要素だけ、その要素の元の値へ
Pythonの`round()`（10進の正しい丸め）を個別に適用して結果を決め直す。

**暗黙の前提**: `material_arrays`は`MATERIAL_CATALOG`の全材料ぶん確保する
（`extractor`未設定の材料も既定値[NaN/False]で確保）。抽出ループ自体は`extractor`を
持つ材料のみ回す。全材料ぶん確保しないと、`extractor`未配線の材料を軸スタジオで
GUI作成した軸を評価した際に`evaluate_axis_array`が`KeyError`で`/api/routes/generate`
自体を落とす（スカラー版`evaluate_axes_scalar`は`materials.get(...)`のためこの経路では
発生しない非対称性がある）。

## タイル単位の静的スコア行列と動的軸合成（探索コストの既定経路）

`RoadGraphEngine`（[routing-engine.md](routing-engine.md)参照）が実際に使う探索コスト
算出の既定経路。探索中にEdge1本ごとにPythonのコスト計算コールバックを呼ぶ構造を避け、
bbox全体ぶんのコストをリクエストにつき1回だけnumpyで合成することで、A*本体へは配列への
`list.__getitem__`だけを渡す。

- **`build_static_edge_score_matrix`**: タイル読込時（`GraphService.
  _get_or_build_tile_materials`）に1回だけ呼び、`_evaluate_axes_bulk`を`wind=None`で
  実行して`StaticEdgeScoreMatrix`（Edge×公開軸の静的スコア行列＋distance_m・
  bearing_deg・0次フィルタ判定用の生配列）を構築する。`infrastructure/
  tile_score_matrix_cache.py`（タイル単位、`graph_material_cache`とは別枠のLRU）へ
  キャッシュされる。
- **`combine_static_edge_score_matrices`**: 複数タイルの`StaticEdgeScoreMatrix`を
  bbox全体1件へ結合する（後勝ちセマンティクス、Edge単位のPythonループを持ち込まない
  numpy fancy indexingで行う）。
- **`DynamicAxisRequestContext`/`DYNAMIC_MATERIAL_EVALUATORS`/
  `evaluate_dynamic_material_arrays`/`evaluate_dynamic_axis_arrays`**: リクエスト時点で
  風などの動的材料（`REQUEST_DYNAMIC_MATERIAL_IDS`）を実際の値へ差し替える。
  `DYNAMIC_MATERIAL_EVALUATORS`は材料id→evaluator関数（Edgeの幾何配列＋動的contextを
  受け取りその材料の配列を返す統一シグネチャ）の登録制ディスパッチで、
  `REQUEST_DYNAMIC_MATERIAL_IDS`と1対1に揃える（現状は`wind_drag_ratio`と非推奨
  エイリアス`wind_penalty`の2件。式の実体は`domain/wind.py`にあり、ここは配線のみ）——
  `REQUEST_DYNAMIC_MATERIAL_IDS`自体が材料id集合として宣言されているため軸id単位では
  なく材料id単位で登録する（`dynamic_axis_topological_order`・`evaluate_axis_array`
  という既存の汎用トポロジカル合成が「動的材料さえ埋まればどんな軸[軸スタジオが
  動的材料を直接参照して作ったカスタム軸を含む]でも正しく合成する」ため、
  軸名のハードコードは呼び出し側に一切現れない）。動的材料が増えたら
  `REQUEST_DYNAMIC_MATERIAL_IDS`とこの辞書へ1エントリずつ追加するだけでよい（CLAUDE.md
  原則1、フロントの`RAMP_AXES`/`buildAxisOverlayLayers`と同種の汎用ディスパッチ）。
  `evaluate_dynamic_material_arrays`が全動的材料を評価する唯一の経路で、スカラー経路
  （`compute_dynamic_edge_materials`、Edge1本を長さ1の配列で呼ぶ薄いラッパー）・
  bulk経路（`_evaluate_axes_bulk`）・静的行列への動的軸合成
  （`evaluate_dynamic_axis_arrays`）の3経路がすべてここを通るため、式が乖離しない。
  `DynamicAxisRequestContext`は出発時点のスナップショット（`weather`）・走行速度
  （`travel_speed_ms`、m/s。既定値を持たない必須フィールドで、伝播漏れは構築時点で
  失敗する）に加え、時刻依存の材料向けに起点の時別予報（`wind_series`）・出発時刻
  （`start`）・Edgeごとの通過予定時刻（`passage_hours`、`bearing_deg`と同じ行順）を持つ。
  3つが揃えば風の材料はEdgeごとにその時刻の風で求め（`wind_inputs()`）、揃わなければ
  スナップショットを全Edgeへ一様に使う。`StaticEdgeScoreMatrix`は通過予定時刻の推定に
  使うEdge中点座標（`mid_lat`/`mid_lon`、from/toノードの平均）も持つ（タイル単位で
  キャッシュ）。
- リクエスト時（`RoadGraphEngine._build_search_graph`）は、`StaticEdgeScoreMatrix`を
  軸id→配列の辞書へ展開→`evaluate_dynamic_axis_arrays`で動的軸を上書き→
  `compose_costs_from_axis_matrix`で重み合成→`compute_hard_filter_excluded`で0次
  フィルタを適用、の順にbbox全体ぶん1回だけ実行してコスト配列を得る。並行Edge
  （同一Node間の複数Edge）はコストが判明済みのため`domain/routing.py:
  build_lazy_road_graph`が「cost最小を採用」する。
  同じコスト配列・軸別スコア配列は`_build_segment_details`（区間表示）からも参照され、
  探索と表示の二重計算を避ける。**唯一の例外**（探索コストのみ補完・表示は変えない、
  `docs/design-principles.md`「探索コストと表示difficultyの一致」参照）: 重み付き軸が
  すべて欠損（composite=NaN）のEdgeは、探索コスト算出にだけbbox内の距離加重平均
  difficultyを代入する（`compose_costs_from_axis_matrix`が内部で
  `distance_weighted_difficulty_array`により算出、`RouteSegmentDetail`側のdifficulty・
  axis_difficultiesはNaN=Noneのまま変わらない）。`_build_search_graph`のINFOサマリ
  （`missing_axis_edges`/`missing_axis_distance_ratio`）でリクエストごとの発生比率を
  観測できる。

## 材料カタログ（`domain/material_catalog.py`）

評価軸が参照する材料（material）の正式カタログ。`MATERIAL_CATALOG: dict[str,
MaterialSpec]`が単一ソース。

`MaterialSpec`の主なフィールド:

| フィールド | 意味 |
|---|---|
| `dtype` | `"numeric"`/`"boolean"`/`"categorical"` |
| `tile_property` | MVTタイルへ既に焼き込み済みのプロパティ名。`None`は「タイル非依存」（地図レイヤーのramp自動生成の対象になりえない） |
| `tile_property_needs_runtime_scale` | タイル側の生値と材料の値がスケール不一致（実行時に変動する係数での変換が必要）か。`derive_ramp_inputs`はこれがTrueの材料を含む軸のramp自動導出を拒否する |
| `tile_property_direction_dependent` | 値が進行方向によって変わる（有向）か。地図のrampレイヤーは単色の線という前提のため、これがTrueの材料を含む軸もramp自動導出を拒否する |
| `primary_attribute_id` | 対応する一次属性id（[軸スタジオ](axis-studio.md)・frontendの`primaryAttributes.ts`が使う名前空間）。材料idと名前が異なるため明示的に対応させる |
| `extractor` | `compute_edge_costs_bulk`の抽出フェーズへ載せる関数。`None`は「専用の計算経路を持つため汎用抽出の対象外」または「トリガー付きDEFER」（利用ニーズが出た時点で配線） |
| `bool_default` | `dtype="boolean"`でextractorが欠損を返したときの配列上の扱い。`"false"`（タグ不在=非該当とみなす多数派）と`"nan"`（不明を非該当と混同しない少数派）の2種で、材料ごとに固定する（数値的に等価ではない） |
| `display_only` | 軸スタジオの材料選択肢（`GET /api/material-catalog`公開レスポンス）から除外し、地図表示専用に限定するか |
| `value_labels` | categorical材料の値ごとの日本語ラベル対訳表（`GET /api/material-catalog/{id}/values`が返す） |
| `reference_points` | 軸スタジオの折れ点編集を助ける「値の目安」一覧（`MaterialReferencePoint`のlabel/value）。値域が直感的でない材料（風等）ほど有用で、真偽値・categorical材料や単純な材料は空リストのままでよい。換算式はbackendだけが持ち、値はここで計算済みのものを持たせる |

- 材料の「登録」（本カタログに載る）と「評価軸での利用」（`AxisDefinition.shape`が
  実際に参照する）は独立している。登録済みでも対応する軸が無ければ評価には使われない
  （軸スタジオの材料選択肢には現れる）。
- 材料自体はGUIから追加・編集・削除できない（コード変更＋デプロイが前提）。軸スタジオ
  は`GET /api/material-catalog`経由で本カタログを動的取得する。
- 風の材料は`wind_drag_ratio`（無次元。相対風速ベクトルの二乗則で求めた、時速20kmで無風の
  ときの空気抵抗を1とする進行方向の抵抗増分。`domain/wind.py: wind_drag_ratio_array`、
  基準速度`WIND_DRAG_REFERENCE_SPEED_MS`は`ASSUMED_SPEED_KMH`とは独立の定数）。
  `wind_penalty`（進行方向に平行な風成分m/s、`headwind_component_ms`）は本番DBの公開軸が
  まだ参照している非推奨エイリアスで、`display_only=True`（軸スタジオの選択肢に出ない）。
  公開軸の参照先が`wind_drag_ratio`へ切り替わった後に撤去する。
- `raw_way_tag_extractor`/`tag_equals_extractor`/`way_tag_parser_extractor`/
  `count_per_km_extractor`という汎用extractorファクトリが用意されており、「単一タグの
  生値取得」「タグ値の単純一致判定」「数値パース」「件数/距離の密度計算」という
  パターンに収まる新規材料は専用のPython関数を書かず、これらへパラメータを渡すだけで
  カタログへ登録できる。優先順位付き分類のような複雑なロジックは専用関数のままでよい。

### 材料カタログのAPI（`api/routers/material_catalog.py`）

| エンドポイント | 認可 | 内容 |
|---|---|---|
| `GET /api/material-catalog` | 不要 | `display_only=False`の材料一覧（`material_id`/`label`[論理名 - 物理名]/`description`/`dtype`/`reference_points`のみ。`tile_property`等のbackend内部フィールドは含めない） |
| `GET /api/material-catalog/{material_id}/values` | 不要 | categorical材料の実データ値一覧（`RegionService.get_material_values`経由、未知idは404・未対応材料/DB未接続は空リスト） |
| `GET /api/admin/material-catalog/coverage` | Basic認証必須 | 材料ごとの欠損割合（下記）。全表走査を伴うため認可なしには公開しない |

## 材料の欠損割合（`infrastructure/material_coverage.py`・`services/material_coverage_service.py`）

欠損データを取込側で推測して埋めるのではなく、欠損の実態を管理画面
（[軸スタジオ管理画面（frontend）](../frontend/axis-studio.md)「材料」タブ）で可視化し、
埋めるかどうかの判断は軸定義側へ委ねる。「欠損」は元データ（OSMタグ・派生テーブルの行）の
不在を指し、評価パイプラインが不在をどう扱うかは`missing_semantics`として併記する。

`MATERIAL_COVERAGE_SPECS: dict[str, WayMaterialCoverageSpec | EdgeMaterialCoverageSpec]`が
材料id→「どの母集団の、どの条件が成り立てば欠損か」の宣言テーブル。

| 母集団 | 対象 | 判定 |
|---|---|---|
| `"way"` | `osm_raw_ways`全行 | `missing_condition`（`osm_raw_ways`の列・`tags` JSONBのみで構成したSQL真偽式、`infrastructure/osm_way_tag_sql.py`の共有断片から組み立てる）。全way材料を`count(*) FILTER`で1回の走査にまとめる（`build_way_coverage_sql`、`FROM osm_raw_ways AS w`）。判定式は[routing-engine.md](routing-engine.md)の`_ROAD_SURFACE_TILE_MVT_SQL`と同じPython定数を参照するため、独立した2つの文字列を突き合わせる形の整合性テストは持たない（同じ定数を使う構成自体が一致を保証する） |
| `"edge"` | `road_edges`全行 | `present_count_sql`（派生テーブル側の「値あり行数」を返すSELECT）。`elevation_attributes`・`edge_attribute_counts`は`edge_id`が`road_edges`へのFK（ON DELETE CASCADE）のため、派生テーブルの行数をそのまま「値ありEdge数」として使いJOINを省く |

- `missing_semantics`: `"unknown"`（欠損は不明値[NaN/None]として扱われ、その材料を使う軸は
  評価対象外になる）／`"definite"`（欠損は確定値[タグ不在=非該当等]として扱われ、軸は
  通常どおり評価される）。`MaterialSpec.bool_default`からは導出しない——`bool_default="nan"`
  でもextractorがタグ不在を確定値として扱う材料（自転車インフラ系5材料）があり、実際の
  扱いはextractorの実装で決まるため、宣言テーブル側に明示する。
- `MATERIAL_COVERAGE_EXCLUSIONS: dict[str, str]`: 集計対象外の材料とその理由（動的計算材料の
  `wind_drag_ratio`/`wind_penalty`、NOT NULL列由来の`oneway`、行の有無がそのまま確定値の
  `designation`系）。
  管理画面はこの理由をそのまま表示する。
- **暗黙の前提**: `MATERIAL_CATALOG`の全材料は`MATERIAL_COVERAGE_SPECS`か
  `MATERIAL_COVERAGE_EXCLUSIONS`のどちらか一方に必ず載る（`test_material_coverage.py`が
  網羅性を検証し、`build_material_coverage_report`はどちらにも無い材料で`ValueError`を
  送出する）。材料を追加したら、どちらかへ1件追加する。
- `MaterialCoverageService.get_material_coverage`はDB例外を握りつぶさず伝播させ、router側で
  503へ変換する（診断用APIのため空レポートへ倒して「欠損0件」に見せない）。
  `api/dependencies.py: get_material_coverage_service`はルート生成用の長い
  `command_timeout`（180秒）を持つセッションを渡す（全表走査がタイル配信用の20秒を
  超えうるため）。

## 区間インスペクタ（`axis_inspector_breakdown`）

単独でクリックされたway（ルート文脈が無い）について、「一次属性→二次軸→三次合成コスト」を
算出する。gradient/windの材料（勾配%・風ペナルティ）は単独wayでは算出不能（ルート沿いの
標高・出発時刻という区間contextが必要）なため常に`available=False`で返す（データ欠損では
なく原理的に算出不能という区別）。`covered_weight_fraction`（全軸の重み合計に対する取得
できた軸の重み合計の割合）をフロントの「参考値」表示に使う。

## タグ正規化（`domain/recipe.py`）

OSMタグ由来の材料タグを正規化する純関数群（`parse_lanes`・`parse_maxspeed`・
`cycleway_values`・`tag_value_is`）。`domain/evaluation.py`・`domain/traffic.py`が
同じ実装を参照する正準1箇所。

`bicycle_infra_flags(tags, highway)`/`bicycle_infra_flags_or_none(tags, highway)`は
自転車インフラの4正規化フラグ（`highway_is_cycleway`・`cycleway_has_track`・
`cycleway_has_lane`・`cycleway_has_shared`）と`shared_pedestrian_path`（河川敷サイクリング
ロード等、highway=footway/pathかつbicycle=yes/designated）を1箇所にまとめる。`_or_none`版は
「タグ自体が未取得」をNoneへ倒すガード条件を1箇所に集約する（呼び出し元4箇所での重複
ガード実装を避ける）。

## RoutePreference（`domain/evaluation.py`）

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

## EvaluationService（`services/evaluation_service.py`）

`load_route_preference()`が既定の`RoutePreference`（`RoutePreference()`、
`default_axis_weights()`由来）を返す。`EvaluationService.evaluate_graph`はI/Oを行わず、
既に取得済みのRoadGraph・属性から`compute_edge_costs_bulk`を呼ぶだけのオーケストレーション層。
探索コストの既定経路（`RoadGraphEngine`）は本クラスを経由しない
（前節「タイル単位の静的スコア行列と動的軸合成」参照）——本クラス自体は
`compute_edge_costs_bulk`のbbox全体一括評価という形を保つオーケストレーション層として
残る（テスト・将来の別呼び出し元向け）。
