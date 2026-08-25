# 推定軸の地図表示自動連動 設計（T308）

ステータス: **ドラフト（2026-08-25起票、設計のみ・実装未着手。ユーザーへ設計を提示済み、
Stage分割や着手順は未承認）**

## 背景

ユーザーからの質問「管理画面で公開した推定要素のみ、地図上でアイコン表示するように
できている？」を発端に調査した結果、現状は**できていない**ことが判明した。

- 地図レイヤー（`frontend/src/components/Map/mapLayers.ts: MAP_LAYERS`）のうち
  静的15項目は完全ハードコード。動的に見える部分（`RAMP_AXES`、
  `frontend/src/components/Map/axisLayers.ts`）も、実行時API`GET /api/axis-catalog`
  （軸スタジオの公開操作が即反映される）ではなく、**ビルド時静的生成物**
  `frontend/src/types/generated/axis-catalog.json`（`backend/scripts/export_openapi.py`が
  `domain/registry.py`のレジストリから書き出す）を単一ソースにしている。
- さらにこのレジストリ自体（`domain/registry_defaults.py: _register_axes()`）は、
  既存7軸だけを1軸ずつ手書きで`register_axis(...)`呼び出しする構造で、`AXIS_DEFINITIONS`
  （DB化済み、軸スタジオがGUIから書き込む単一ソース）を走査する経路が存在しない。
  つまり**軸スタジオで新規作成・公開した軸は、ramp化可能な材料構成であっても、
  ビルド時生成物を再生成・再デプロイしても地図には一切現れない**（配信経路が
  そもそも無い）。
- 地図に現れる既存7軸のうち、`surface_q`・`night`のみが`domain/axis_display.py:
  derive_ramp_inputs()`により材料定義から自動導出されている。`car_stress`・
  `stop_density`・`accident`は`registry_defaults.py`に`tile_inputs`/`thresholds`を
  直接手書きしている（`derive_ramp_inputs`が「複数材料の重み付き結合」「タイル値と
  スケールが異なる材料」を安全側で自動導出対象外にしているため）。

ユーザーの認識確認（2026-08-25のやり取り）:
- 「推定軸の色分け（凡例）はMVTタイルには一切焼き込まれていない」→**その通り**。軸の色は
  タイルには入っておらず、フロント（`MapView.tsx`のMapLibre `line-color`式、
  `axisLayers.ts: buildAxisRampColorExpression`）がタイル焼き込み済みの**材料の生値**を
  その場で合成して求めている。
- 「軸スタジオで指定した条件でMVTタイルを演算すれば導出できる、それを『既存合成した
  結果』と呼んだ」→この理解も正確。材料さえタイルに焼き込み済みなら、軸の合成式
  （どの材料をどんな重みで）から色分け情報を導出するのに**新しいタイル焼き込み作業は
  不要**——問題は「導出ロジック（`derive_ramp_inputs`）の対応範囲が狭い」ことと、
  「導出した結果を配る経路がビルド時生成物止まり」であることの2点（後述Gap1・Gap2）。
- 「推定軸の材料によって対応が変わると考える。動的要素が絡むものや、観測要素の中でも
  向きがあるものは、時間や有向表現の検討が必要」→設計に反映（後述「除外条件」）。

## ギャップの整理

- **Gap 1（配信経路）**: `is_published`の切替（軸スタジオでの公開操作）が即座に反映される
  実行時API（`GET /api/axis-catalog`）と、地図表示が実際に読むビルド時静的生成物
  （`axis-catalog.json`）が別物。かつそのビルド時生成物を作る`registry_defaults.py`の
  レジストリ自体が7軸ハードコードで、GUI作成軸を含む一般化された走査がそもそも無い。
- **Gap 2（導出ロジック）**: `derive_ramp_inputs`が対応できる材料構成が狭い
  （単一材料のCategoricalShape[bool2値のみ]・FlagSumShape・単一材料/weight=1.0の
  BreakpointLinearShape）。複数材料の重み付き結合（`car_stress`・`stop_density`相当の
  構成）は自動導出できず、軸スタジオでユーザーがGUIから作れる軸の多く
  （`AxisComposer.tsx`は複数`MaterialTerm`を重み付きで組み合わせる「区分線形補間」を
  標準の作成手段として提供している）が対象外になってしまう。

## 目標

1. Gap 1: 軸スタジオでの公開操作が、フロントの再デプロイなしに地図表示へ反映される。
2. Gap 2: タイル焼き込み済み・実行時スケール変換不要・方向非依存の材料だけで構成された
   軸であれば、`registry_defaults.py`への個別の手書き登録なしに、ramp表示
   （`tile_inputs`/`thresholds`）が自動導出される。
3. 上記2点で解決できない材料（タイル非依存・実行時スケール変換要・方向依存）は、
   安全側で「地図に出さない」（`kind="none"`）へ倒し、ユーザーに実装時に明示する
   （黙って間違った色を出さない）。

## 設計

### Gap 1: 配信経路をビルド時静的生成物→実行時APIへ

**現状**: `GET /api/axis-catalog`は`AXIS_DEFINITIONS`（プロセス内、書き込み時にin-place
更新済み）を都度読んで返す——`label`/`description`/`category`/`default_weight`のみ。
地図表示に要る`display`（kind/tile_inputs/thresholds等）は含まれておらず、地図側は別の
ビルド時生成物を見ている。

**変更方針**:

1. `axis_display_for(definition: AxisDefinition) -> AxisDisplaySpec`という関数を
   `domain/axis_display.py`へ新設する。中身は「①既存7軸のうち自動導出不可な3軸
   （car_stress・stop_density・accident。理由はGap2の対応後に再確認、対応できたものは
   ①から外す）向けの手書きoverride表（現行`registry_defaults.py`の該当箇所を移設）を
   引く、②無ければ汎用化した`derive_ramp_inputs(definition)`を呼ぶ、③どちらも
   得られなければ`kind="none"`」という優先順位。純粋関数（`AXIS_DEFINITIONS`と
   `MATERIAL_CATALOG`というプロセス内メモリだけを見る、DB/IO無し）なのでAPIリクエスト毎に
   呼んでもコストは無視できる。
2. `GET /api/axis-catalog`のレスポンス（`AxisCatalogEntry`）へ`display`フィールドを追加し、
   `is_published=True`の軸すべてについて`axis_display_for()`の結果を含める。これにより
   軸スタジオでの公開操作が**即座に**（DB書き込み→`AXIS_DEFINITIONS`のin-place更新→次の
   API呼び出し、既存のpush型更新の仕組みそのまま）反映される。
3. フロント: `axisLayers.ts`の`RAMP_AXES`（現状ビルド時静的`axis-catalog.json`を
   importして`display.kind==="ramp"`でフィルタ）を、`useAxisCatalog.ts`と同じパターンの
   フック（例: `useAxisCatalog`自体に`display`を含めて返すよう拡張、または専用の
   `useAxisRampLayers`）へ置き換える。取得完了まで・失敗時は現行の静的
   `axis-catalog.json`フォールバック（既存7軸のみ）のままなので、後退（既存機能が
   壊れる）は無い。
4. `MAP_LAYERS`（`mapLayers.ts`、静的15項目 + `RAMP_AXES.map(...)`のモジュール直下
   定数）は、フック取得値に依存する形へ構造変更が要る。`page.tsx`・
   `MapLayersPanel.tsx`が直接`import { MAP_LAYERS }`している箇所を、
   「静的15項目（引き続き定数）」＋「フックが返す動的ramp軸配列」を呼び出し側で
   結合する構成（例: `buildMapLayers(rampAxes: RampAxis[]): MapLayerDescriptor[]`という
   純粋関数化＋各コンポーネントで`useMemo`結合）へリファクタする。影響箇所の洗い出しは
   実装着手時に`MAP_LAYERS`の全参照箇所（page.tsx・MapLayersPanel.tsx、および間接的に
   MapOverlayControls.tsx等）を再確認する。

### Gap 2: `derive_ramp_inputs`の汎用化

現行の制約と、それぞれ撤廃できるかの判断:

| Shape | 現行の制約 | 撤廃できるか | 根拠 |
|---|---|---|---|
| `CategoricalShape` | `mapping`のキーがbool 2値のみ（str N値は`None`） | **できる** | `registry.py: TileInputSpec.categories`は既にN値文字列材料に対応済み（`car_stress`のhighway/bicycle_infra/designationが実例）。閾値は`sorted(set(mapping.values()))`の隣接中点（bool2値の`[(lower+upper)/2]`をN値へ一般化するだけ）。`has_unknown_fallback=True`固定（T297の教訓通り、未登録値=評価不能という`evaluate_categorical`の意味論に合わせる） |
| `FlagSumShape` | 制約なし（既に一般化済み） | (変更不要) | — |
| `BreakpointLinearShape` | 単一`term`・`weight==1.0`・`preprocess=="identity"`のみ | **`weight`・`term`数の制約は撤廃できる**。`preprocess=="abs"`は当面維持 | `total = Σ(material_value × term.weight)`という評価側の量は、`TileInputSpec(property, weight=term.weight)`をtermごとに並べてフロントが計算する量と**完全に同一**（同じ材料・同じ重み・同じ演算）。`preprocess="identity"`ならbreakpoint補間の入力がこの`total`そのものなので、`shape.breakpoints[1:]`のx値は元のterm数・重みに関わらずそのまま妥当な閾値になる（近似ではなく数学的に厳密な流用）。`abs`はフロントの`buildAxisRampValueExpression`が未対応のため、対応するまでは引き続き自動導出対象外とする（フォローアップ、本タスクのスコープ外） |

**新たな除外条件（ユーザー指摘、2026-08-25）**: 動的要素（風など時間で変わる材料）や、
観測要素でも進行方向によって値が変わりうる材料（有向）は、1本の線を単色で塗る
ramp表示には単純化できない（時間表現は`DynamicLayerTimeSlider`、方向表現は矢印等の
専用実装が要る——既存の風レイヤー・降水ナウキャストと同じ枠組みが必要で、tile_inputsの
単純な重み付き和では表現できない）。`tile_property_needs_runtime_scale`と同じ設計で、
`MaterialSpec`へ`tile_property_direction_dependent: bool = False`を新設し、
`derive_ramp_inputs`が`True`の材料を含む軸を除外条件に加える。現行`MATERIAL_CATALOG`に
方向依存材料の実例は無い（`oneway`は表示専用の一次属性でどの軸の材料にもなっていない、
T289）が、将来方向依存材料が追加された際に安全側へ倒す型的な安全弁として今のうちに
用意する。

### 軸スタジオ（GUI）への付随改善案（必須要件ではない）

`AxisComposer.tsx`の材料選択肢は`GET /api/material-catalog`由来で内部詳細
（tile_property等）を返さない設計を維持しつつ、軸の保存前後に「この軸は地図に
表示されます/されません（理由: ○○が地図タイルに含まれないため等）」を軸スタジオの
一覧・編集画面へ出せると運用上親切（`axis_display_for()`の結果[kind]を管理API
レスポンスへ含めるだけで実現可能）。本タスクの必達要件ではなく、実装時に余力があれば
含める付随案として記録するに留める。

## 段階分け（規模が大きいため2段階を想定）

- **Stage A（Gap 2、backend単独）**: `derive_ramp_inputs`の汎用化＋
  `MaterialSpec.tile_property_direction_dependent`新設。既存7軸のうち`car_stress`・
  `stop_density`・`accident`の手書き`display`が汎用化後のロジックで再現できるか検証し、
  再現できるものは`registry_defaults.py`の手書きを削減する（完全一致を既存テストで
  担保）。
- **Stage B（Gap 1、backend API + frontend）**: `GET /api/axis-catalog`への`display`
  同梱＋フロントのRAMP_AXES取得を実行時APIベースへ切替＋`MAP_LAYERS`動的結合の
  リファクタ。Stage Aの汎用`derive_ramp_inputs`を前提とするため、Stage A→Bの順で
  進める。

## 影響範囲・リスク

- `registry.py`/`registry_defaults.py`のAPIサーフェス変更は既存テスト
  （registry関連のtest_*.py）に影響する可能性が高く、Stage A実装時に丁寧に確認する。
- Stage Bのフロント変更は`MAP_LAYERS`を直接importしている複数箇所
  （`page.tsx`・`MapLayersPanel.tsx`、間接的に`MapOverlayControls.tsx`）に影響するため、
  影響範囲の洗い出しを実装着手時に改めて行う。
- 材料の天井（目論見書7章・歯止め4）・材料の排他帰属チェック（T268）など既存の歯止めとは
  独立した変更であり、これらの制約自体には触れない。

## 未解決・要ユーザー判断

- Stage A・Bどちらから着手するか、両方まとめて一度に実装するか。
- 軸スタジオの「地図表示プレビュー」UXを本タスクのスコープへ含めるか。
- 既存7軸のうち自動導出可能になったものについて、手書き`display`を削減するところまで
  踏み込むか（コード削減・二重管理の解消というメリットがある一方、既存の表示が
  一字一句変わらないことの検証コストが増える）、それとも新規GUI軸だけを対象にして
  既存7軸の手書きはそのまま残すか（後者の方が安全でスコープが小さい）。
