# ルート設定・結果パネル（frontend）

## 責務

一般ユーザー向けのルート生成条件入力（距離・重み・除外道路）と、生成結果の表示・比較
（軸別内訳・候補一覧・研究モードの実験スロット比較）を担う。

**対象ファイル**

| ファイル | 責務 |
|---|---|
| `components/RouteForm/RouteForm.tsx` | 距離入力・生成ボタン。周回/目的地モード切替 |
| `components/RouteSettingsPanel/RouteSettingsPanel.tsx` | 一般向け軸重み設定・除外道路・地図色分けトグル |
| `components/WeightPanel/WeightPanel.tsx` | 研究モード向けのscoring_weights（distance/difficulty）編集 |
| `components/WindBearingSlider/WindBearingSlider.tsx` | 走行方位の指定コンパススライダー（風・勾配で再利用） |
| `components/RouteList/RouteList.tsx` | 生成候補の一覧表示 |
| `components/RouteAxisProfile/RouteAxisProfile.tsx` | 選択中ルートの軸別difficulty横棒グラフ |
| `components/ComparisonPanel/ComparisonPanel.tsx` | 研究モードの実験スロット比較表 |
| `hooks/useAxisCatalog.ts` | `GET /api/axis-catalog`取得。軸一覧・既定重み・ramp軸・軸ラベル・二次軸・ルート色分けモードを一括提供 |
| `services/axisCatalogApi.ts` | 上記フックが叩くbackend APIの薄いラッパー |
| `lib/evaluationAxes.ts` | `PREFERENCE_AXES`（ルート設定・軸別内訳の並び順）・`SCORING_AXES`（distance/difficulty） |
| `lib/routePreferenceSync.ts` | `route_preference`のキー集合をカタログへ同期する共通ロジック |
| `components/Map/recipeControls.tsx`（`FieldLabel`・`withAutoEnable`・`RecipePanelSection`） | 上書き有効化・情報アイコン付きラベルの共有UI部品 |

## RouteSettingsPanel.tsx（一般向けメイン設定面）

```
useAxisCatalog() ──→ catalog.axes（公開軸一覧、is_published=Trueのみ）
                          │
        ┌─────────────────┼───────────────────────┐
        ▼                                          ▼
  重み配分バー（帯グラフ、境界              軸の凡例チップ（折り返して並ぶ）:
  ドラッグ/矢印キーで隣接2軸の重みを        色ドット+ラベル（タップで有効/無効）+
  移し替え）                                (i)説明文ポップオーバー +
        │                                   地図色分けアイコン（対応軸のみ）
        │                                          │
        └──────────────┬───────────────────────────┘
                        ▼
        走行方位設定ポップオーバー（風・勾配のうち色分けONの
        軸が1件以上あるときだけ現れるボタン）
                        │
                        ▼
              除外する道路（Disclosure折りたたみ）
```

- 軸の一覧・既定重みは`useAxisCatalog`経由（取得完了まで・失敗時は既存軸の静的
  フォールバック）。軸スタジオでの追加が再デプロイなしに反映される。
- カテゴリ（観測/推定/動的）によるグルーピング表示は行わない（軸スタジオが常に
  `category="推定"`固定で軸を作るようになったため、フラットな1本のリストにした）。
- 重み配分バー（帯グラフ、`stackBarOuter`/`stackBarHandle`）は表示専用ではなく、
  隣り合う2区間の境界（`role="slider"`のハンドル、幅16px）をポインタドラッグまたは
  矢印キーで操作すると、その両隣の2軸間でだけ重みが移動する（他の軸・2軸の合計は
  変わらない、`clampBoundaryDrag`が範囲[`WEIGHT_STEP`, 0.6]内へクランプする）。
  ハンドル自身だけに`touch-action: none`を絞ってあり、帯グラフの他の部分（セグメント
  本体）はスクロールジェスチャーを妨げない。**重みの調整手段はこの帯グラフの
  ドラッグ・矢印キー操作のみ**——0.01刻みで1軸だけを狙う個別スライダーは持たない。
  帯の色（`stackBarColorForIndex`、実際の軸数でHSL色相環を等分）と凡例チップの
  色ドットは同じ関数・同じindexから生成しており、常に一致する。「重み配分」見出し脇の
  情報アイコン（`stackBarLegendTrigger`）を押すと、全軸ぶんの色ドット+ラベル+現在の%を
  一覧するポップオーバーが開く。境界をドラッグしている間だけ、そのハンドルの直上に
  両隣2軸の%をフロート表示する（`stackBarDragBadge`、ドラッグ終了で消える）——native
  title属性のホバーツールチップ（モバイルでは事実上見えない）の代わり。
- 軸の凡例チップ（`renderLegendChip`）は「色ドット+ラベル（タップで有効/無効を
  切替、weight>0が有効の判定基準）」「(i)説明文ポップオーバー」「地図色分けアイコン
  （地図表示に対応する軸だけ、`renderLegendMapColorToggle`）」の3要素で構成される
  複合ボタン群。無効な軸（weight=0）はチップ全体を半透明にする。地図表示に対応しない
  軸は色分けアイコンごと出さない。
- `mapColorLayerIdFor(axisId)`: 軸id→地図色分けレイヤーIDの解決。
  (1) `catalog.secondaryAxes`（`components/Map/secondaryAxes.ts`由来、ramp表示を持つ軸）に
  あればそのレイヤーID、(2) 無ければ`axis.dedicatedWayValueLayer`
  （`AxisDefinition.dedicated_way_value_layer`）を見て`${axisId}Axis`という命名規則から
  `isDedicatedWayValueLayerId`型ガードで機械的に導出する（[地図: 軸・ルート色分け](map-axis-coloring.md)参照）。どちらも無ければ地図表示非対応（凡例チップにアイコンを出さない）。
  **`secondaryAxes.ts`はこのモジュールの対象ファイル表に無いが、`useAxisCatalog`の
  `secondaryAxes`フィールドを介してこのパネルの地図色分けトグル解決ロジックに
  直接組み込まれている**（本来の所有元は[地図: 静的レイヤー・道路表示](../frontend/static-map-layers.md)系のモジュール）。
- ルート確定後（`hasDetail=true`）は、専用way_id配信レイヤーを持つ軸（風・勾配）の
  色分けアイコンを、案内文（title/aria-label）つきの無効化アイコンへ切り替える——
  ルート確定後はこれらの軸が「生成したルートの色分け」側の役割になるため。
- 向きコンパス（`WindBearingSlider`、`renderBearingControl`）は、風・勾配の色分けが
  ONになっている間だけ現れる「走行方位を設定」ボタン（`activeBearingAxes`が1件以上
  返すときのみ表示）から開くRadix Popoverの中にまとめて表示される。凡例チップ自体には
  埋め込まない（コンパスのドラッグ操作がtouch-action: noneの領域を持つため、常時
  表示のチップ列に置くとスクロールを妨げる）。
- `routePreference`（送信対象）とカタログのキー集合を`syncRoutePreferenceKeys`で
  双方向同期する（軸の追加/unpublishに追従。backendは「上書きするなら既知の全axis_id
  キー一致」を要求するため、ズレるとルート生成が422になる）。
- 除外する道路（0次フィルタ）は`Disclosure`で折りたたみ表示。既定値のまま変えていない
  利用者が大半のため既定で閉じるが、既に変更済みの場合（`hardFilterCustomized`）は
  「変更していることに気づかず開けない」事故を避けるため既定で開く。
- `resetButton`（既定値に戻す）は`routePreference`・`hardFilters`の両方を一括で初期状態へ戻す。

**暗黙の前提**: `useAxisCatalog()`は`page.tsx`と`RouteSettingsPanel.tsx`から同時に呼ばれうる
（`page.tsx`がマウントした時点で子の`RouteSettingsPanel`も同時マウントされるため）。
モジュールレベル変数`inFlightCatalogFetch`で同時フェッチを重複排除するが、解決/失敗したら
即座にクリアし結果を永続キャッシュしない（軸スタジオでの公開操作を再デプロイなしに
反映するという設計を保つため、後続の別マウント[モバイルのBottomSheetを開き直す等]では
改めて最新を取得する）。

**暗黙の前提（`loaded`フラグの意味）**: `AxisCatalog.loaded`は「取得成功し他フィールドが
実際のDB由来の値であること」を表す。`loaded=false`（未取得/失敗）の間は他フィールドが
ビルド時静的フォールバックの可能性があるため、「軸スタジオの現在の公開軸集合と一致して
いなければならない」処理（`route_preference`のキー整合等）ではこのフラグで未確定状態を
区別しなければならない。取得成功時に軸が0件（全軸非公開）であっても`loaded=true`になる
（0件も確定した実際の状態のため）。

## WeightPanel.tsx（研究モード）

`RouteSettingsPanel`とは別の入口（研究モード向け）。`ScoringWeights`
（`distance_weight`/`difficulty_weight`の2指標）を編集する。`route_preference`
（軸ごとの重み）自体を編集するUIは持たない（`RouteSettingsPanel`側が担う）。初期値の
定数export（`DEFAULT_ROUTE_PREFERENCE`、`axis-catalog.json`の`preference_defaults`由来）は
`page.tsx`・admin側が参照する。

## WindBearingSlider.tsx（走行方位スライダー、風・勾配で再利用）

`@fseehawer/react-circular-slider`（TypeScript対応・依存無し・MIT）を使ったコンパス型UI。
`value`/`onChange`/`ariaLabel`のみを扱う汎用コンポーネントで、時刻には一切関与しない
（時刻は別の共有タイムライン`DynamicLayerTimeSlider`が担当）。風・勾配の両方で
`page.tsx`が`windBearingDeg`/`gradientBearingDeg`という独立したstateで本コンポーネントを
2箇所マウントする。

`cardinalLabel(bearingDeg)`（0〜360度→8方位の日本語ラベル）は`backend/app/domain/geo.py:
compass_label`と同じラベル配列・丸めアルゴリズムをfrontend側に持つ。
`WindBearingSlider.test.ts`が既知の入出力ペアでbackendとの一致を検証する。

## RouteAxisProfile.tsx（選択中ルートの軸別内訳）

`RouteCandidate.axis_difficulties`（axis_id→difficulty 0-100の距離加重平均）を、
`useAxisCatalog().axes`の並び順で横棒グラフ表示する。評価できなかった軸（キー自体が
無い）は表示しない。色は`axisLayers.ts: rampColorForBand`（地図の段階配色と同じ配色系統）
を`bandCount=101`で流用し、0-100の連続値をそのまま色へ変換する。

## RouteList.tsx / ComparisonPanel.tsx

- `RouteList.tsx`: 候補一覧のラベルを評価軸カタログ（`SCORING_AXES`）から動的生成する
  （軸を増やしてもこのファイルを直接編集する必要が無い）。`total_score`は同一generate
  呼び出し内でのみ比較可能な相対値であることを明記する説明文を先頭に添える。
- `ComparisonPanel.tsx`: 研究モードの実験スロット比較表。表示順は
  (1) 生の物理量（距離・獲得標高・風スコア・舗装率。単位・意味がaxis_difficultiesとは
  異なる別系統のフィールドのため区別して残す）→
  (2) 個別軸の生値行（`axisLabels`・`axes`をpage.tsxから受け取り、
  `RouteCandidate.axis_difficulties`から動的生成。軸スタジオの軸増減に自動追従する）→
  (3) 全軸合成の総合難易度（`overall_difficulty`、末尾固定）。`total_score`は実験間
  比較表には出さない（相対評価の誤用防止をUIで強制する設計）。

## RouteForm.tsx

距離入力・生成ボタン。`RouteMode`（"loop"|"destination"）で周回/目的地モードを切り替える。
モバイル上部バー向けの`compact`表示を持つ。目的地モードでは距離を入力させず、経由地・
目的地のいずれも未指定のまま生成しようとするとサイレント失敗せずエラー文言を出す。
