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

軸単位の評価（[軸スタジオ](axis-studio.md)の`priority_overrides`、材料の値が一致すれば
評価を優先確定する仕組み）とは別の概念——0次フィルタは道路そのものを探索グラフから
除外する。

## 軸別スコア → difficulty合成

```
compute_edge_axis_scores(edge, ...)
        │  材料を解決し、軸スタジオのevaluate_axes_scalarへ渡す
        ▼
  軸id → difficulty(0-100) の辞書
        │
        ├──→ composite_difficulty(scored_weights)      : 複数軸を重み付き合成 → 1つのdifficulty
        └──→ distance_weighted_difficulty(segments)     : 複数区間を距離加重平均 → ルート全体のdifficulty
```

- `evaluate_axis_difficulties`（`difficulty.py`）が`AxisDifficulties`（NamedTuple）を
  組み立てる。
- 探索コスト用には`compute_edge_cost`（1Edge）・`compute_edge_costs_bulk`（numpy配列版、
  `_neumaier_accumulate`でNeumaier加算により浮動小数点誤差を抑制）が
  `compute_cost_from_axis_scores`経由でRoutePreferenceの重みを掛けて1つのcostへ合成する。

## 材料カタログ（`domain/material_catalog.py`）

評価軸が参照する材料（material）の正式カタログ。**単一ソース**——以前はフロント側
`axisMaterialsCatalog.ts`が独自にハードコードしていたが、本モジュールへ一本化した。

- 材料の「登録」（本カタログに載る）と「評価軸での利用」（`AxisDefinition.shape`が
  実際に参照する）は独立している。登録済みでも対応する軸が無ければ評価には使われない
  （軸スタジオの材料選択肢には現れる）。
- 材料自体はGUIから追加・編集・削除できない（コード変更＋デプロイが前提の設計）。
  軸スタジオ（`/admin`）は`GET /api/material-catalog`経由で本カタログを動的取得する。
- 新しい材料を追加するときは本ファイルへ1件追加するだけで、フロントのコード変更・
  再デプロイなしに軸コンポーザーの選択肢へ現れる。

## タグ正規化（`domain/recipe.py`）

OSMタグ由来の材料タグを正規化する純関数群（`parse_lanes`・`parse_maxspeed`・
`cycleway_values`・`tag_value_is`等）。`domain/evaluation.py`・`domain/traffic.py`・
`services/openrouteservice_engine.py`が同じ実装を参照する正準1箇所。

## 候補集合内の相対スコアリング（`domain/scoring.py`）

`normalize_min_max(values, higher_is_better)`: 同じ`generate_loops`呼び出し内の候補
同士をmin-max正規化して0-100点化する（異なるリクエスト間では比較不可な相対スコア）。
[ルート生成エンジン](routing-engine.md)の`RouteScorer`（services層）がこれを使って
`total_score`を算出する——本モジュールは正規化の純関数のみを持ち、`RouteScorer`自体は
ルート生成エンジンモジュール側にある。

## EvaluationService（`services/evaluation_service.py`）

`load_route_preference()`が既定の`RoutePreference`（重み・0次フィルタ上書き）を読む。
`EvaluationService`はリクエストの上書きと組み合わせて実際に使う`RoutePreference`を組み
立てる。
