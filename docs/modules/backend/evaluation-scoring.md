# 評価・スコアリング（backend）

## 責務

道路のEdge/区間から、0次フィルタ判定・軸別difficulty・合成difficulty・探索用cost・
候補集合内の相対スコアを算出する。軸ごとの評価式自体（`AxisDefinition.shape`の評価）は
[軸スタジオ・評価軸定義](axis-studio.md)が持ち、本モジュールはその1段上（材料の解決・
複数軸の合成・0次フィルタ）を担う。

**対象ファイル**

| レイヤー | ファイル |
|---|---|
| domain | `evaluation.py`・`difficulty.py`・`material_catalog.py`・`recipe.py`・`scoring.py` |
| services | `evaluation_service.py` |

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
        │  compute_edge_axis_scores(edge, elevation_attribute, surface_type, wind, ...)
        │  MATERIAL_CATALOGの各extractorが材料値（材料id→スカラー値）を組み立てる
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

## `compute_edge_costs_bulk`（numpyベクトル化版）

`EvaluationService.evaluate_graph`（road_graphエンジンの探索コスト算出、既定のホット
パス）専用。`compute_edge_cost`を全Edge分ループするのと同じ結果を、Pythonループ無しの
numpy配列演算で算出する。

- **抽出フェーズ**（1回のPythonループ）: `MATERIAL_CATALOG`の`extractor`宣言を使い、
  Edge単位の辞書・タグアクセスをすべてnumpy配列へ落とし込む。材料を1件追加する際は
  `material_catalog.py`へ抽出関数を登録するだけでよく、この関数自体の変更は不要。
- **計算フェーズ**（Pythonループ無し）: 材料id→配列の辞書に対して`AXIS_DEFINITIONS`を
  軸ごとに適用しdifficulty配列を求め、重み配列とのマスク付き加重平均→cost算出まで
  すべて配列演算で行う。スカラー経路（`compute_edge_axis_scores`）と同じ軸定義データを
  読むため、軸の追加は定義データの追加だけで両経路へ同時に反映される。
- スカラー版`compute_edge_cost`は削除せず、本関数との出力一致を検証する回帰テストの
  オラクルとして残る。

**暗黙の前提（浮動小数点の一致）**: `_neumaier_accumulate`（Neumaier補償加算のnumpy版）は
Python組み込み`sum()`（Python 3.12以降、Neumaier補償加算を使う）とビット単位で同じ
結果を返すために存在する。単純な逐次`+=`ではちょうど.X5境界の値で最終丸め結果が
`compute_edge_cost`（スカラー版）と食い違う。最終丸めも同じ理由でnumpyの`np.round`
ではなくPythonの`round()`を要素ごとに適用する（`round1_array`）。

**暗黙の前提**: `material_arrays`は`MATERIAL_CATALOG`の全材料ぶん確保する
（`extractor`未設定の材料も既定値[NaN/False]で確保）。抽出ループ自体は`extractor`を
持つ材料のみ回す。全材料ぶん確保しないと、`extractor`未配線の材料を軸スタジオで
GUI作成した軸を評価した際に`evaluate_axis_array`が`KeyError`で`/api/routes/generate`
自体を落とす（スカラー版`evaluate_axes_scalar`は`materials.get(...)`のためこの経路では
発生しない非対称性がある）。

## 材料カタログ（`domain/material_catalog.py`）

評価軸が参照する材料（material）の正式カタログ。`MATERIAL_CATALOG: dict[str,
MaterialSpec]`が単一ソース。

`MaterialSpec`の主なフィールド:

| フィールド | 意味 |
|---|---|
| `dtype` | `"numeric"`/`"boolean"`/`"categorical"` |
| `tile_property` | MVTタイルへ既に焼き込み済みのプロパティ名。`None`は「タイル非依存」（地図レイヤーのramp自動生成の対象になりえない） |
| `tile_property_inverted` | タイル側の生値の符号反転が必要か（例: `no_lit`はタイルの`lit`の否定） |
| `tile_property_needs_runtime_scale` | タイル側の生値と材料の値がスケール不一致（実行時に変動する係数での変換が必要）か。`derive_ramp_inputs`はこれがTrueの材料を含む軸のramp自動導出を拒否する |
| `tile_property_direction_dependent` | 値が進行方向によって変わる（有向）か。地図のrampレイヤーは単色の線という前提のため、これがTrueの材料を含む軸もramp自動導出を拒否する |
| `primary_attribute_id` | 対応する一次属性id（[軸スタジオ](axis-studio.md)・frontendの`primaryAttributes.ts`が使う名前空間）。材料idと名前が異なるため明示的に対応させる |
| `extractor` | `compute_edge_costs_bulk`の抽出フェーズへ載せる関数。`None`は「専用の計算経路を持つため汎用抽出の対象外」または「トリガー付きDEFER」（利用ニーズが出た時点で配線） |
| `bool_default` | `dtype="boolean"`でextractorが欠損を返したときの配列上の扱い。`"false"`（タグ不在=非該当とみなす多数派）と`"nan"`（不明を非該当と混同しない少数派）の2種で、材料ごとに固定する（数値的に等価ではない） |
| `display_only` | 軸スタジオの材料選択肢（`GET /api/material-catalog`公開レスポンス）から除外し、地図表示専用に限定するか |
| `value_labels` | categorical材料の値ごとの日本語ラベル対訳表（`GET /api/material-catalog/{id}/values`が返す） |

- 材料の「登録」（本カタログに載る）と「評価軸での利用」（`AxisDefinition.shape`が
  実際に参照する）は独立している。登録済みでも対応する軸が無ければ評価には使われない
  （軸スタジオの材料選択肢には現れる）。
- 材料自体はGUIから追加・編集・削除できない（コード変更＋デプロイが前提）。軸スタジオ
  は`GET /api/material-catalog`経由で本カタログを動的取得する。
- `raw_way_tag_extractor`/`tag_equals_extractor`/`way_tag_parser_extractor`/
  `count_per_km_extractor`という汎用extractorファクトリが用意されており、「単一タグの
  生値取得」「タグ値の単純一致判定」「数値パース」「件数/距離の密度計算」という
  パターンに収まる新規材料は専用のPython関数を書かず、これらへパラメータを渡すだけで
  カタログへ登録できる。優先順位付き分類のような複雑なロジックは専用関数のままでよい。

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

## 候補集合内の相対スコアリング（`domain/scoring.py`）

`normalize_min_max(values, higher_is_better)`: 同じ`generate_loops`呼び出し内の候補
同士をmin-max正規化して0-100点化する（異なるリクエスト間では比較不可な相対スコア）。
`None`はそのまま`None`を返す。全候補が同値の場合は中立の100点を返す。
[ルート生成エンジン](routing-engine.md)の`RouteScorer`（services層）がこれを使って
`total_score`を算出する——本モジュールは正規化の純関数のみを持ち、`RouteScorer`自体は
ルート生成エンジンモジュール側にある。

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
`preference`は呼び出し元（`RoadGraphEngine.prepare`）が必ず明示的に渡す（night軸の動的
重み付けを反映したコピーを渡すため、`EvaluationService`自身が保持する`self._preference`は
直接使わない）。
