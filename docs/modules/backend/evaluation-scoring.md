# 評価・スコアリング（backend）

## 責務

道路のEdge/区間から、0次フィルタ判定・軸別difficulty・合成difficulty・探索用cost・
候補集合内の相対スコアを算出する。軸ごとの評価式自体（`AxisDefinition.shape`の評価）は
[軸スタジオ・評価軸定義](axis-studio.md)が持ち、本モジュールはその1段上（材料の解決・
複数軸の合成・0次フィルタ）を担う。

**対象ファイル**

| レイヤー | ファイル |
|---|---|
| domain | `evaluation.py`（Edge Costの算出。探索範囲の静的スコア行列と、コストの合成・逆算）・`hard_filters.py`（0次フィルタ）・`route_preference.py`（重み指定）・`dynamic_materials.py`（風などリクエスト時に決まる材料）・`axis_inspector.py`（区間インスペクタ）・`difficulty.py`（軸の得点の合成と、区間からルートへの集約）・`material_catalog.py`・`material_sql.py`（材料の値をSQLで導出する式。道・ノードの生データを読む副問い合わせは`infrastructure/source_models.py`） |
| services | `material_coverage_service.py` |
| infrastructure | `material_coverage.py`（材料ごとの欠損割合の集計クエリ） |
| api | `material_catalog.py`（材料カタログ・材料値一覧・欠損割合のエンドポイント） |

domainのファイルは**変更理由で分けてある**。`evaluation.py`が変わるのはコストの
計算方法を変えるとき、`hard_filters.py`はフィルタを増減するとき、`route_preference.py`は
APIが受け取る重みの形を変えるとき、`dynamic_materials.py`は動的材料を増やすとき、
`axis_inspector.py`は区間インスペクタの内訳表示を変えるとき。

`material_sql.py`が**domainにある**のは、材料が何から導かれるかがdomainの知識だから。
[routing-engine.md](routing-engine.md)の`ROAD_SURFACE_TILE_MVT_SQL`と本モジュールの
`material_coverage.py`が同じ式を参照する——infrastructureの各所がそれぞれSQLを書くと、
一方だけ変わったときに気付けない。

**材料の導出は`MaterialSpec.value_sql`1本**。評価・地図タイル配信・欠損率の集計・
軸スタジオの値列挙は、すべて同じ式を読む。入力に対するあるべき値は
`tests/test_material_values.py`が期待値の表で固定する。式が実在の列と、読み出しの経路ごとのFROM句に
ある別名だけを読むことも同じファイルが見る——値の表は別名を値で与えるため、綴りの合わない列や、
経路に無い別名（路面タイルの`re`等）を読む式は、値の表だけでは見つからない。

**タイルへ焼く列は、値式を載せ方で包むだけ**。`tile_property`を持つ全材料について、タイルの列を
`domain/material_catalog.py: tile_column_sql`が値式から組み、路面タイルの文
（`road_graph_repository.py: ROAD_SURFACE_TILE_MVT_SQL`）は`material_tile_columns`をそのまま並べる——材料を1つ足せば
タイルにも列が増え、式を直せば地図と評価が一緒に変わる（タイルの形の署名も変わり、配信中のタイルは作り直しになる）。
`tile_property`を持つ材料は値式を必ず持つ（宣言の検証が断る）。載せ方は型ごとに決まる:

| 型 | 載せ方 |
|---|---|
| 真偽 | `CASE WHEN (value_sql) THEN true END`。「該当しない」をNULLへ畳み、フィーチャーからキーを省いてタイルを軽くする。タグの不在を「不明」とする真偽の材料（`coverage.missing_semantics`が`"unknown"`）はこの載せ方の対象外で、タイルへ焼くなら「不明」を値として持つ分類の材料にする（例: 路面の見込み） |
| 分類 | 値式をそのまま |
| 数値 | `MaterialSpec.tile_encoding`の形（丸めの桁・0の省略・倍精度）で包む。例: 密度は小数1桁へ丸め、0を省く |

材料の値1つがタイルにどう載るかを、`tile_property_value`がPythonの値で返す（画面へ配る期待値の表がタイルのプロパティを作るのに読む）。
SQLの式と値の関数が同じ値を出すことは、`tests/test_material_values.py`が同じあるべき値を両方へ当てて見る。

タイルの文は、値式が読む別名をフィーチャーの単位で与える。区間単位のフィーチャーは`em`が区間の値・
`re`の長さが区間の長さ、way丸ごとのフィーチャーは`em`が道1本の値の同じ名前の列（無い列はNULL）・`re`の長さが
wayの長さ（0はNULL）になる——件数と長さは必ず同じ側から取る。実行時の係数で割る材料
（`tile_property_runtime_scale`）は割る前の値を焼き、係数の源が値式で読むSQLの引数
（`TILE_RUNTIME_SCALE_SQL_PARAMS`）をタイルの文では1で束ねる（`tile_unscaled_sql_params`）。

## 0次ハードフィルタ（`domain/hard_filters.py`）

`compute_hard_filter_excluded`が、材料の表から読んだフィルタ名→該当フラグの配列と、
リクエストが指定した有効なフィルタ名の集合から、Edgeごとの除外を求める。`hard_filters`
省略時は`DEFAULT_HARD_FILTERS`（宣言されている全フィルタが常時有効）を使う。

**受け取るフラグのキー集合は宣言と完全一致でなければ落ちる**——欠けたフィルタは黙って
無効になり、高速道路や`bicycle=no`の道がそのまま候補へ入る。リクエスト側の名前も宣言に
無いものは要求の検証（`api/routers/routes.py: HardFilterOverride`）が拒む（綴り間違いと「そのフィルタを切った」を
区別できないため）。

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
  可能なため0次のハード除外対象にはせず、軸の側（材料`motor_vehicle_no`）で扱う。

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

way粒度の経路も**区間向けと同じ式**を使う。`way_from_clause`がwayの行から同じ名前の
エイリアス（`wm`/`re`/`em`）を組み立てるだけで、式を2組持たない。
区間の値を持つ`em`は、way粒度では道1本の値の同じ名前の列を引く別名になる——**区間の値をway1本へ
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
        │  観測を引く材料（雨）は探索範囲を組むときに区間の中点に最も近い雨量計の今の観測を
        │  列として足す（`RoadGraphEngine`の気象の段が観測を読み→`domain/rain.py: rain_material_columns`）
        │  動的材料（風）だけはリクエスト時に`evaluate_dynamic_material_arrays`が
        │  bearing配列・天候・走行速度から求める
        ▼
  二次: 軸id → difficulty(0-100) の辞書
        │  domain/axis_definitions.py: evaluate_axes_array が AXIS_DEFINITIONS を評価
        │  （軸が他の軸のdifficultyをmaterialとして参照する階層構造も含む）
        ▼
  三次: compose_costs_from_axis_matrix(distance_m, axis_arrays, weights, penalty_strength)
        │  difficulty = Σᵢ wᵢ × axisᵢ / Σᵢ wᵢ（difficulty.py: composite_difficulty_array）
        │  cost = 下地 × (1 + P × difficulty / 100)
        ▼
  cost・difficulty配列（0次フィルタの除外は`compute_hard_filter_excluded`が別途判定）
```

way1本を指す区間インスペクタも同じ評価・合成を長さ1の配列で通す（`axis_inspector_breakdown`→
`evaluate_axes_values`・`difficulty.py: composite_difficulty`）。軸の評価と合成の式は配列版の
1本ずつで、入口ごとに書き写さない——書き写すと、区間を押して見える得点とルート選びが使う得点が
同じ道で食い違う。

- 評価できなかった軸は合成から除外され、残りの重みで再正規化される。
- `penalty_strength`（P）は**主観的割増と時間の換算レート**。リクエストが省略したときの値は
  較正値`evaluation.penalty_strength`（`domain/tuning.py`）だけが持ち、`resolve_penalty_strength`が
  リクエスト処理時に読む（`compose_costs_from_axis_matrix`は既定を持たない）。探索のコストは
  `所要時間 × (1 + P × difficulty/100)`＝体感の所要時間で、P=1は「難易度100の道は
  体感で2倍の時間」を意味する。P=0で`cost=下地`（好みを一切考慮しない＝時間最短、
  `select_fastest_route`が返す基準線と同じ物差し）、Pを上げるほど悪路が強く避けられる。
  `cost >= 下地`という不変条件はP>=0の間常に成り立つ（下地は探索では区間ごとの
  所要時間、Edge単位の評価では距離）。
- **`build_static_edge_score_matrix`**: `AXIS_DEFINITIONS`を軸ごとに適用して
  difficulty配列を求める（`StaticEdgeScoreMatrix`: 公開軸別配列に加え、0次フィルタ判定用の
  生フラグ`hard_filter_flags`/`gradient_percent`も持つ——`hard_filters`はリクエストごとに
  変わりうるため、除外判定そのものはここでは確定させない）。動的材料
  （`REQUEST_DYNAMIC_MATERIAL_IDS`、風）の列はNaNのままで、それに依存する軸の列も自然に
  NaNへ伝播する（動的軸の特別扱いが不要）。観測を引く材料（雨、`observed_materials`）はDBの材料と
  同じ列として重ねる——向きにも通過の時刻にも依らず、生成1回につき1つの値で済むため、軸の得点・
  生値（mm）・内訳にDBの材料と同じ経路で載り、道の材料と1つの軸で組み合わせることもできる（動的材料は
  静的材料と同じ軸に置けない。`axis_definitions.py: _check_dynamic_and_static_materials_are_not_mixed`）。
  観測の履歴が無ければ空で、その材料を読む軸はその生成で「データなし」になる。
- **`compose_costs_from_axis_matrix`**: 軸別スコア配列群と重み辞書から合成difficulty
  （`difficulty.py: composite_difficulty_array`）→cost算出まで配列演算で行う。costからdifficultyへの
  逆算（折返し点・経由Nodeの並べ替えが使う）は同じファイルの`difficulty_from_cost`が持つ。0次フィルタによる除外
  （`compute_hard_filter_excluded`が`hard_filters`/`max_average_grade_percent`を反映して
  別途判定）はここには含まれない。重み付き軸がすべて欠損のEdgeはcost算出だけbbox内平均
  difficultyを代入する（表示用の戻り値には影響しない、詳細は後述「探索コストの既定経路」節）。

**暗黙の前提（浮動小数点の丸め）**: 合成の和は補償加算（`difficulty.py: _neumaier_accumulate`）で
求める。単純な逐次`+=`では誤差が項の数だけ積み上がり、真の値がちょうど.X5境界にある合成値の
最終丸めが誤差の向きしだいで別の側へ倒れる。最終丸めは難易度の桁（`difficulty.py: DIFFICULTY_DECIMALS`）の`round()`と同じ値へ丸める
（`round_difficulty_array`）。`×10→np.rint→÷10`を配列全体で
まとめて計算し、計算後の値がちょうど`.5`に乗った要素だけ、元の値と10進の中点の大小を
仮数の整数で正確に比べて決め直す（配列のまま。要素ごとにPythonの`round()`を呼ぶと、
小数1桁の得点を重み0.5ずつ足した軸・同じ重みの2軸の合成のように半数近くの要素が`.5`に乗る入力で、
時刻のビンごとに評価し直す動的軸の合成が1回あたり数十ms重くなる）。軸1本の得点
（`evaluate_axis_array`）も同じ`round_difficulty_array`で丸める。

**暗黙の前提**: 軸が読む材料の配列は`MATERIAL_CATALOG`の全材料ぶん確保する
（`value_sql`を持たない材料も既定値[NaN/False/値なし]で確保）。確保しないと、値式が無い材料を
軸スタジオでGUI作成した軸を評価した際に`evaluate_axis_array`が`KeyError`で
`/api/routes/generate`自体を落とす（Pythonの値の入口`evaluate_axes_values`は、無い材料を
全要素欠損の列として埋めてから配列へ通す）。

## 探索範囲の静的スコア行列と動的軸合成（探索コストの既定経路）

`RoadGraphEngine`（[routing-engine.md](routing-engine.md)参照）が実際に使う探索コスト
算出の既定経路。探索中にEdge1本ごとにPythonのコスト計算コールバックを呼ぶ構造を避け、
bbox全体ぶんのコストをリクエストにつき1回だけnumpyで合成することで、A*本体へは配列への
`list.__getitem__`だけを渡す。

- **`build_static_edge_score_matrix`**: 生成のたびに、切り出した探索範囲の材料
  （`GraphService.get_search_slice`）と雨の観測（`RoadGraphEngine`の気象の段）から`StaticEdgeScoreMatrix`（Edge×公開軸の静的スコア行列＋distance_m・
  bearing_deg・0次フィルタ判定用の生配列、行は切り出した区間の順）を構築する。キャッシュしない——
  軸定義の編集がそのまま次の生成に効く。`asyncio.to_thread`の先で組むため、軸定義は入口で写し
  （`axis_definitions.py: copy_axis_definitions`）を1回取り、組み終えるまでそれだけを読む（軸の保存と重なっても、
  列は1つの軸の集合から組まれる。[軸スタジオ](axis-studio.md)「ライフサイクル」）。
  分類の材料（`highway`・路面の見込み等）は、道路網の置き場が持つ語彙への番号の列
  （`domain/attributes.py: CategoricalColumn`）のまま受け取って運ぶ。軸の対応表・0次条件・走行モデルの
  転がり抵抗は、語彙の値ごとに1回引いた表を番号で配る——区間ごとに値の文字列へ戻して1件ずつ引くと、
  区間数に比例したPythonの仕事になり、探索範囲の広い生成では1回に数秒単位で効く。
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
  `REQUEST_DYNAMIC_MATERIAL_IDS`とこの辞書へ1エントリずつ追加するだけでよい（
  [設計原則](../../architecture/design-principles.md)構造仕様8、フロントがramp軸をカタログ［`axisCatalog.rampAxes`］から列挙して塗るのと同種の汎用ディスパッチ）。
  `evaluate_dynamic_material_arrays`が全動的材料を評価する唯一の経路で、静的行列への
  動的軸合成（`evaluate_dynamic_axis_arrays`）もここを通るため、式が乖離しない。
  `DynamicAxisRequestContext`は出発時点の風のスナップショット（`departure_wind`）・走行速度
  （`travel_speed_ms`、m/s。既定値を持たない必須フィールドで、伝播漏れは構築時点で
  失敗する）に加え、時刻依存の材料向けに時別予報（`wind_series`、格子点ごと）・出発時刻
  （`start`）・Edgeごとの通過予定時刻（`passage_hours`）と最寄りの格子点（`wind_points`。どちらも
  `bearing_deg`と同じ行順）を持つ。
  これらが揃えば風の材料はEdgeごとにその時刻の風で求め、揃わなければ
  スナップショットを全Edgeへ一様に使う。風は進行方向の成分と横成分に分けて
  （`wind_components_ms`、contextごとに1回だけ求める）読み、走行モデルも同じ成分を読む。
  `StaticEdgeScoreMatrix`は通過予定時刻の推定と風の格子点の引き当てに使うEdge中点座標
  （`mid_lat`/`mid_lon`、from/toノードの平均）も持つ（キャッシュしない）。
- リクエスト時（`RoadGraphEngine._build_search_graph`）は、`StaticEdgeScoreMatrix`を
  軸id→配列の辞書へ展開→`evaluate_dynamic_axis_arrays`で動的軸を上書き→
  `compose_costs_from_axis_matrix`で重み合成→`compute_hard_filter_excluded`で0次
  フィルタを適用、の順にbbox全体ぶん1回だけ実行してコスト配列を得る。並行Edge
  （同一Node間の複数Edge）は`domain/routing.py: build_lazy_road_graph`が元の行（切り出した区間の順）の
  最も小さい1本を採る決定的な規則で解消する（コストはリクエストごとに変わるため見ない）。
  時刻ビンごとに合成し直すときの、風に依らない計算の使い回しは[routing-engine.md](routing-engine.md)
  「レグ別コスト配列」節。
  同じコスト配列・軸別スコア配列は`_build_segment_details`（区間表示）からも参照され、
  探索と表示の二重計算を避ける。区間の軸別寄与度（表示用）は`difficulty.py: axis_contributions_at_row`が
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
| `overall_difficulty.average` | 距離加重平均（`route.py: merge_difficulty`。密度の軸の分は下の「密度の軸」） | 距離で正規化されるため、遠回りして難所を避けるほど下がる。候補の並び順はこの昇順 |
| `overall_difficulty.load` | 平均×距離合計（`route.py: merge_overall_difficulty`） | 距離が伸びればそのまま増える。「走り切るまでのしんどさ」に近く、遠回りが不利に出る |

平均と総量は同じ区間から一緒に決まる（平均が出なければ総量も出ない）ため、1つの任意の項目
`overall_difficulty`にまとめて返す。

距離加重平均は、区間の並び（Pythonの値）を受ける`weighted_mean_by_distance`と、探索範囲全体の
配列を受ける`distance_weighted_difficulty_array`の2本が同じ規則（値の無い区間は分母からも外す・
距離の合計が0以下ならNone）を持つ。前者を配列へ並べ替えて後者を通すと、1呼び出しあたりの所要が
数µsから十数µsへ増え（区間5〜20件で2〜4µs→10〜14µs）、ビンごと・値の種類ごとに呼ぶルートの
集約で積み上がるため、2本のままにしている。

**密度の軸は、得点ではなく回数を平均してから得点にする。** 軸の折れ線の横軸の値が1kmあたりの量（密度）の重み付き和の軸
（`evaluation.py: averages_density`。足せる材料`MaterialSpec.additive`だけを項に持ち、前処理が無い）は、ビン（500m）と候補の
得点を、区間の得点の平均ではなく、横軸の値を距離で平均した値（その範囲の回数÷距離）を折れ線に通して作る。折れ線は上に凸で
上限で頭打ちになることが多く、信号が交差点の脇の短い区間に集まる幹線では、区間ごとの得点の平均が回数どおりの得点よりずっと
低く出る（都内の国道6号で回数どおり65.7点のところ40.3点）。勾配のように密度でない材料の軸・他の軸を項に持つ軸は得点の平均の
まま（短い急坂を平均でならすと坂のつらさが消える）。
- 運び方: 静的スコア行列が密度の軸の横軸の値の列（`StaticEdgeScoreMatrix.density_axes`）を持ち、`LegCostArrays.density_axes`を
  経て、`_build_segment_details`が区間ごとの値・丸めない距離・その軸の重みの割合（`difficulty.py: axis_weight_shares_at_row`）を
  区間の器の内部の値（`RouteSegmentDetail._density_inputs`。応答に出ない）として載せる。距離を丸めないのは、応答の区間の距離が
  10m単位で、信号の脇の数mの区間が長さ0になって回数ごと消えるため。
- 畳み方（`route.py`）: 得点は横軸の値の距離平均を折れ線に通した値（`merge_axis_difficulties`）、寄与度はその得点×重みの割合の
  距離平均（`merge_axis_contributions`）、合成の難しさは区間の値の距離加重平均の、その軸の寄与度の項だけを作り直した寄与度へ
  差し替えた値（`merge_difficulty`。寄与度の和と合成の難しさの関係を保つ）。ビンは区間から、候補はビンからもう一度同じ畳み方で作り、
  ビンも中の区間の平均を内部の値として持つ。順回り・逆回りの比べ（`route_search.py: pick_better_candidate`）も同じ`merge_difficulty`を読む。
- 探索の費用は区間ごとの得点の和のままで、この畳み方を持たない（区間ごとに費用を足すA*へは、区間をまたいだ平均をそのまま持ち込めない）。

同じ集約を軸の**生値**（折れ点を通す前の値、`StaticEdgeScoreMatrix.axis_raw_values`）にも
掛ける。区間の応答は生値を持たず、エンジンがEdge単位の生値を区間と同じ切り方でビンへ畳んでから
候補全体へ畳む（`road_graph_engine.py: _build_candidate`→`route.py: route_axis_raw_values`→
`RouteCandidate.axis_raw_values`）。得点0-100は目盛りの引き方に依存する相対評価のため、
軸単体で経路を判断するには絶対値が要る。生値を持つのは単位が定まる軸
（[軸スタジオ](axis-studio.md)「生値の単位」節）だけで、かつリクエストごとに変わる
材料（風等）を参照する軸は静的スコア行列へ載らないため対象外。

**単位が定まらない軸は、代わりに材料まで分解した絶対量を持つ。** 分解は
`axis_raw_value.py: axis_material_shares`が軸定義から機械的に行い、軸参照
（内部軸）は葉の材料まで再帰的に辿る——途中の軸の得点は内訳に含めない。
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
`StaticEdgeScoreMatrix.categorical_material_ids`/`categorical_material_columns`
（語彙への番号の列、列を決める述語は`route_facing_categorical_material_ids`）→
区間ごとの値（`road_graph_engine.py: _build_segment_details`が区間の並びと対で返す。
区間の器`RouteSegmentDetail`は約500mのビンへ畳まれ、分類値はビンの代表値1つにすると
割合がビンの粒度へ量子化されるため、器には載せない）→
`merge_material_category_shares`（距離加重で「値ごとの延長割合」へ畳む。分母はその材料の値を
持つ区間だけで、値の無い区間は分母にも入れない）→`RouteCandidate.material_category_shares`。
真偽値材料を0/1で運んで平均が割合になるのと同じ考え方を、値が3つ以上ある材料へ広げたもの。

**丸めは値の種類で分ける**。距離加重平均そのものは`weighted_mean_by_distance`
（`domain/difficulty.py`、丸めない）が求め、丸め方は呼び出し側が決める——
difficulty系（0〜100）は難易度の桁（`difficulty.py: round_difficulty`。候補の並びの同点もこの桁で決まる）、生値・材料値は**有効数字4桁**。
生値のスケールは軸ごとに違い（勾配は`%`で0〜15程度、事故密度は`件/(km・年)`で
有効域0〜0.5）、固定の小数桁で丸めると桁の小さい軸で値がまるごと潰れて
「値が無い道」と区別できなくなる。frontendの表示（`axisRawValue.ts: formatNumber`）も
同じ理由で1未満は有効数字2桁を残す。

総量は順位付けには使わず、平均と併せて判断材料として返す。difficultyが
Noneの区間の扱いは平均と一致させる（区間ごとに積分して欠損を飛ばすと、データの無い区間が
多いルートほど総量が小さく見えてしまうため、平均×全区間の距離合計で求める）。

## 材料カタログ（`domain/material_catalog.py`）

評価軸が参照する材料（material）の正式カタログ。`MATERIAL_CATALOG: dict[str,
MaterialSpec]`が単一ソース。

`MaterialSpec`の主なフィールド:

| フィールド | 意味 |
|---|---|
| `dtype` | `"numeric"`/`"boolean"`/`"categorical"` |
| `unit` | 値の単位（凡例・数値表示用、無次元・真偽値・カテゴリ値は空文字）。生成物`material-catalog.json`がfrontendへ届け、frontendは単位を持たない（唯一の正）。**`label`へ単位を書かない**——ラベルと単位を別々に組み立てる画面で「制限速度(km/h) 35km/h」のように二重になる |
| `additive` | 同じ単位の他の材料と**足し合わせて意味を持つ量**か（示量／示強の区別）。個数と、それを同じ距離で割った密度はTrue。%・km/h・倍率のような割合・率はFalse。`raw_value_unit`が2項以上の和を見せてよいかの判定に使う |
| `total_unit` | 生値へ走行距離を掛けた**総量**を出すときの単位（出す意味が無ければ`None`）。`additive`とは別の問い——事故密度（件/[km・年]）は足せるが、総量に比べる尺度が無い。|
| `tile_property` | MVTタイルへ既に焼き込み済みのプロパティ名。`None`は「タイル非依存」（地図レイヤーのramp自動生成の対象になりえない）。列は`value_sql`から組む（上の「タイルへ焼く列」） |
| `tile_encoding` | 数値の材料をタイルへ載せる形（`TileEncoding`: 丸めの桁・0の省略・倍精度）。ST_AsMVTはnumeric型を文字列で載せるため、丸めた値は倍精度へ戻す |
| `tile_property_runtime_scale` | タイル側の生値を材料の値へ換算する係数が実行時にしか決まらないときの、係数の源（例: 事故の収録年数の逆数）。地図表示の自動導出はこの材料のタイル入力に`needs_runtime_scale`の印を付け、係数は`GET /api/axis-catalog`の`tile_runtime_scales`（`domain/material_catalog.py: tile_runtime_scales`が宣言から導く）で配る。ほかの軸が参照する折れ点の軸の材料だと、その参照は地図に畳めない（タイル入力は係数を掛ける前に折れ点を当てる形を表せない） |
| `tile_property_direction_dependent` | 値が進行方向によって変わる（有向）か。地図のrampレイヤーは単色の線という前提のため、これがTrueの材料を含む軸もramp自動導出を拒否する |
| `primary_attribute` | 対応する一次属性（`PRIMARY_ATTRIBUTES`の宣言そのもの。idの文字列では指さない。[軸スタジオ](axis-studio.md)「一次属性の語彙」節）。材料idと一次属性id（frontendの`primaryAttributes.ts`が使う名前空間）は名前が異なるため明示的に対応させる |
| `weather_grid_value` | 材料が読む自前のMSM格子の値（例: 風）。一次属性を持たない動的な材料の元データを、同じ格子の値を描く気象のチップ（`domain/weather_elements.py: WeatherElement.grid_value`）が地図に見せる。`GET /api/axis-catalog`はこれを軸ごとに`weather_layer_groups`へ解決し、地図の説明文がその評価の名前を差し込む |
| `value_sql` | その材料の値をDBから求めるSQL式。`None`は「SQLでは求められない」（リクエスト時に決まる風、評価へ配線していないトリガー付きDEFER）。タイルへ焼く材料は必ず持つ |
| `coverage` | 欠損率の測り方。way単位・区間単位・対象外の3択で、**どれかを必ず持つ**（どちらの一覧にも載っていない材料を型として作れなくする） |
| `value_labels` | categorical材料の値ごとの日本語ラベル対訳表（生成物`material-catalog.json`と`GET /api/admin/material-catalog/{id}/values`が届ける） |
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
- 材料自体はGUIから追加・編集・削除できない（コード変更＋デプロイが前提）。frontendが材料を知る
  経路はビルド時の生成物`material-catalog.json`（`scripts/export_openapi.py`）だけで、実行時のAPIでは
  配らない——材料は再デプロイでしか変わらないため、実行時に取りに行くと取得失敗という状態だけが増える。
  生成物の`label`は「論理名 - 物理名」（`MaterialSpec.full_label`、軸スタジオ向け）、`name`は論理名だけ
  （一般向けの画面・地図のポップアップ向け）。
- コードが名指しで読む材料（例: 勾配・風・路面の良否）は、同じファイルのid定数（`GRADIENT_PERCENT`等）で
  指し、カタログのキーにも同じ定数を使う。文字列で書き写すと、綴りがずれたときに読む側が材料を
  見つけられず、黙って欠損（区間の表示から値が消える・全区間が舗装路扱いになる等）として扱う。
- 風の材料は`wind_drag_ratio`（無次元。相対風速ベクトルの二乗則で求めた、時速20kmで無風の
  ときの空気抵抗を1とする進行方向の抵抗増分。`domain/wind.py: wind_drag_ratio_array`、
  基準速度`WIND_DRAG_REFERENCE_SPEED_MS`は`ASSUMED_SPEED_KMH`とは独立の定数）。
- 土地被覆の割合材料は`edge_materials.lc_*`／`way_materials.lc_*`（区間単位・way単位、
  [静的道路属性・タイル配信](static-road-attributes.md)）が持つクラス別の割合で、
  **どのクラスが割合列を持つかは`landcover.py: LANDCOVER_CLASSES`が単一の正本**で、
  列指向テーブル・集計SQL・読み出し・タイルの焼き込み列は、そこからクラス値の昇順で
  導いた`PERCENT_CLASSES`を読む。材料もクラスの宣言から1クラス1材料で生成する（材料idは割合列の名前、
  表示名はクラスの表示名から作る）ため、クラスを足せば材料も揃って増える。列・焼き込みの名前の規則
  （`lc_<鍵>`・材料の`tile_property`＝焼き込み列の名前）は`landcover.py: landcover_key`・
  `landcover.py: landcover_tile_property`だけが持つ——材料の`tile_property`と焼き込み列の名前がずれると、地図は黙って塗らない。
  **材料の値式は`em.lc_*`だけを読み、区間の値が無いときに道1本の値へ落とさない**——区間の値は全区間ぶん
  計算されており、落とす先は同じ道の平均でしかない。道1本を単位に値を求める文脈
  （`road_graph_repository.py: material_from_clause`が`em`を道1本の行へ読み替える）では道の値になる。
  路面タイルと区間インスペクタ（`get_feature_landcover`）も、フィーチャーの単位（区間かway丸ごとか）で
  読む列を選ぶ——単位を揃えないと、同じ場所で地図の色と内訳の数字が食い違う。

  **欠損判定に1クラスを名指ししない。** 判定も読み出し列もクラスの宣言から導く
  ——名指しすると、クラスを1つ足して既存行を埋め戻す前に、その列がNULLというだけで
  行ごと捨てる。
  **1つの軸で複数のクラスを足さないこと**——割合の合計が100%へ固定されているため
  同じ地面を二重に数える（[設計原則](../../architecture/design-principles.md)構造仕様14）。
- 値式は`domain/material_sql.py`の組み立て関数から作る（タグの正規化・タグ値の一致・
  数値パース・件数の密度化・タグが無いときの非該当）。同じ判定を材料ごとに書き写さないため、
  判定を直すと全材料へ同時に効く。

### 値式が参照するエイリアス

値式は**材料の数が増えてもエイリアスが増えない**形で設計する。元データの出どころごとに
1つのエイリアスを用意し、材料はそのどれかの列を指す。

| エイリアス | 元データ | ここから生える材料 |
|---|---|---|
| `w` | 生の道（`source_features`の`source='osm_way'`を、よく引くタグを列へ出した副問い合わせ。`infrastructure/source_models.py: ways_source_sql`） | `surface`・`lit`・`maxspeed_kmh`・`bridge`・`smoothness`等 |
| `re` | 区間の行（`road_edges`） | `highway`・距離（密度の分母） |
| `em` | 区間に付く値（主キーが区間の鍵の派生の表） | 標高・件数の密度・区間単位の土地被覆 |
| `wm` | 道1本に付く値（主キーが道の鍵の派生の表） | way単位の土地被覆・道の曲がり具合等 |

`em`・`wm`を与えるJOINは、どの経路でも`road_graph_repository.py: material_from_clause`が組み立てる。式が読む列を
宣言（`derived_models.py`）から引き、その列を持つ表だけを主キーで外部結合する。宣言に無い列を読む式は組み立てる時点で
送出し、区間の表どうし（道の表どうし）が同じ名前の列を持つとimportの時点で送出する（別名の列の出どころが決まらない）。

way粒度で引くときは、同じ式のまま`w`の行から同じ名前の別名を組み立てる
（`road_graph_repository.py: way_from_clause`）。`em`はway側の同名列かNULLを返す1行になる
ため、区間にしか無い値（標高）はNULLになる。

**行の有無と値の有無を分ける。** `w`の行が無い（求めた区間がDBに無い・取込で消えた道を、派生を
作り直すまでの区間が指す）ときはタグ由来の材料が不明（NULL）になり、行があればタグが無くても非該当（false）として
確定する（`tag_absent_is_false_sql`。真偽の材料（照明・橋・トンネル・自転車道の有無等）が使う）。ルート選びの配列でも
真偽の材料は数値の行列に1.0/0.0で載り、不明は`NaN`のまま届く（`material_catalog.material_array_columns`）——真偽の行列に
載せると欠損を持てず、不明が非該当に化ける。件数も同じで、集計行が無ければ不明、行があれば
載っていないキーは0件。集計前を0件として読むと、全区間が「停止要因ゼロ＝最も易しい」と
評価されてルート選択が静かに歪む。

`MaterialDType`（`numeric`/`boolean`/`categorical`）は、元データの出どころを
増やしても増えない。

**エイリアスを足してよいかの判定基準**: その材料の兄弟が今後増えるなら、既存の
エイリアスの列として足す。新しいエイリアスを足すのは、元データの表そのものが増えるとき
だけ（読む経路のFROM句の全部へ同じ名前で用意する必要がある）。区間・道の値の表を足すだけなら、`em`・`wm`の列が
増えるだけで別名は増えない。

### 材料カタログのAPI（`api/routers/material_catalog.py`）

材料の一覧そのものはAPIで配らない（上記）。ここにあるのは実データを読まないと答えられないものだけ。

| エンドポイント | 認可 | 内容 |
|---|---|---|
| `GET /api/admin/material-catalog/{material_id}/values` | HTTP Basic | categorical材料の実データ値一覧（`services/axis_preview_service.py: AxisPreviewService`経由、未知idは404・値一覧を持たない材料は空リスト・DB障害やタイムアウトは`available=false`）。索引の効かない`SELECT DISTINCT`をルート生成用の長い`command_timeout`のセッションで実行する。繰り返し呼ばれるだけで接続を占有できるため、`coverage`と同じく認可を課す |
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
| `"way"` | 生の道の全行（`infrastructure/source_models.py: WAYS_SOURCE_SQL`） | `missing_condition`（生の道の列・`tags` JSONBのみで構成したSQL真偽式、`domain/material_sql.py`の共有断片から組み立てる）。全way材料を`count(*) FILTER`で1回の走査にまとめる（`build_way_coverage_sql`、`FROM {WAYS_SOURCE_SQL} AS w`）。判定式は[routing-engine.md](routing-engine.md)の`ROAD_SURFACE_TILE_MVT_SQL`と同じPython定数を参照するため、独立した2つの文字列を突き合わせる形の整合性テストは持たない（同じ定数を使う構成自体が一致を保証する） |
| `"edge"` | `road_edges`全行 | `present_condition`（区間の値（別名`em`）が値を持つときに真のSQL条件式）。`road_edges`へ区間の値を読み出しと同じ結び方（`material_from_clause`）で外部結合し、全edge材料を`count(*) FILTER`で1回の走査にまとめる（`build_edge_coverage_sql`） |

- **「行がある」と「値がある」を混同しない**。派生の表は区間ごとに行を持ち、値を出せない列は
  NULLのまま残す（土地被覆の`lc_*`がそう。NULLの意味は[静的道路属性](static-road-attributes.md)「値が無ければNULL」）。
  行の有無だけで数えると、値がNULLの行を「データあり」と数えてしまう。判定は評価が実際に読む**列**のNULLまで見る。
- `missing_semantics`: `"unknown"`（欠損は不明値[NaN/None]として扱われ、その材料を使う軸は
  評価対象外になる）／`"definite"`（欠損は確定値[タグ不在=非該当等]として扱われ、軸は
  通常どおり評価される）。宣言はタグの不在の意味で、値の式がそれに合わせて`NULL`か`false`を返し、配列では読み替えない
  （真偽の材料はどちらでも数値の行列へ載り、`NULL`を`NaN`で持つ）。地図の不明の帯（`axis_display.py`）もこの宣言から引く。
- `CoverageExcluded(reason=...)`: 集計対象外の材料とその理由（動的計算材料の
  `wind_drag_ratio`、NOT NULL列由来の`oneway`、生データの道のCHECK`source_features_way_has_kind`でhighwayを必ず持つ`highway`・`highway_is_cycleway`等）。
  欠損し得ない材料を集計対象へ置かない——欠損の判定が常に0件を数える式になり、DBが持つ前提を式の側でもう一度持つことになる。
  管理画面はこの理由をそのまま表示する。
- **どちらか一方を必ず持つことは型が保証する**: `MaterialSpec.coverage`は必須で、
  way単位・Edge単位・対象外の3択（`MaterialCoverage`）のいずれかしか取れない。
  「どちらの一覧にも載っていない材料」を作れないため、網羅性を確かめるテストは要らない。
- `MaterialCoverageService.get_material_coverage`はDB例外を握りつぶさず伝播させ、管理API共通の例外の扱い
  （`api/admin_db_errors.py`）が503で返す（診断用APIのため空レポートへ倒して「欠損0件」に見せない）。
  `api/dependencies.py: get_material_coverage_service`はルート生成用の長い
  `command_timeout`（180秒）を持つセッションを渡す（全表走査がタイル配信用の20秒を
  超えうるため）。
- 欠損の扱いと母集団の画面の名前（管理画面の欠損率の見出し・説明）は、同じファイルの`MISSING_SEMANTICS_DISPLAY`・`POPULATION_LABELS`が持ち、生成物`vocabulary.ts`で画面へ届く。

## 区間インスペクタ（`axis_inspector_breakdown`）

単独でクリックされたway（ルート文脈が無い）について、「一次属性→二次軸→三次合成コスト」を
算出する。材料値は`RoadGraphRepository.get_way_material_values`が返したものをそのまま受け
取り、この関数は合成だけを行う。進行方向に依存する材料（勾配%・風ペナルティ）は
**1本の道が往復2方向で違う値を持つ**ためDBのway単位の値には無く、走行方位・時刻・想定速度を
指定して呼び出し側（`services/dedicated_way_values.py: DirectionalMaterialService`）が引いたものを
`materials`へ足して渡す。足されなければその軸の`difficulty`はNoneになる。合成
（`composite_difficulty`）は値と`covered_weight_fraction`（全軸の重み合計に対する取得できた軸の
重み合計の割合）を1つの任意の項目で持ち、取得できた軸が無ければNone。割合はフロントの
「参考値」表示に使う。


## RoutePreference（`domain/route_preference.py`）

`weights: dict[str, float]`（axis_id→重み、既定値は`default_axis_weights()`）。
既定の重みの入口は`RoutePreference()`だけで、組み立てるたびにその時点の公開軸から導く
（ルート生成・区間インスペクタのどちらも、重みを省略されたらこれを使う）。
部分指定を許し、書かれなかった公開軸は`default_weight`で補う。値の不変条件は`check_axis_weights`が持ち、
組み立てるたびに通す——キーは公開軸（`is_published=True`）のidだけ（内部軸は重み付けの対象外）、値は有限かつ非負
（負の重みは合成difficultyの分母と分子の符号を食い違わせ、NaN・無限大は合成difficultyと寄与を黙って欠損にする）。ルート生成の要求を通らずに組み立てる書き手
（研究のスクリプト・テスト）も同じ検査を通る。「上書きするなら公開軸を全部書く」は要求の形で、
`api/routers/routes.py: RoutePreferenceWeights`が持ち、値の検査は同じ`check_axis_weights`を呼ぶ。

時間帯を持つ軸（`time_scope`が`"always"`以外）の重みは`RoutePreference`では切り替えない——区間を通る時刻で
区間ごとに決まるため、合成器が`domain/axis_definitions.py: time_scoped_weights`で区間ごとの配列にする
（[routing-engine.md](routing-engine.md)「夜間軸の動的重み付け」）。
