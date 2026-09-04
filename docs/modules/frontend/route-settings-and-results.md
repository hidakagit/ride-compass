# ルート設定・結果パネル（frontend）

## 責務

一般ユーザー向けのルート生成条件入力（距離・重み・除外道路）と、生成結果の表示・比較
（軸別内訳・候補一覧・研究モードの実験スロット比較）を担う。

**対象ファイル**

| ファイル | 責務 |
|---|---|
| `components/RouteForm/RouteForm.tsx` | 距離入力・候補件数入力・巡航速度入力・生成ボタン。周回/目的地モード切替 |
| `components/RouteSettingsPanel/RouteSettingsPanel.tsx` | 一般向け軸重み設定・除外道路・地図色分けトグル |
| `components/WindBearingSlider/WindBearingSlider.tsx` | 走行方位の指定コンパスダイヤル（`TravelBearingControl`から使われる。単体としての設置場所は[ページ全体構成・状態管理](page-composition.md)参照） |
| `components/RouteAxisProfile/RouteAxisProfile.tsx` | 候補ごとのタブの中身（地図の色分けチップ列＋「重み付き寄与度」内訳）。候補一覧のタブ自体はpage.tsxが直接組み立てる（[ページ全体構成・状態管理](page-composition.md)参照） |
| `components/RouteAxisProfile/AxisContributionBar.tsx` | 「重み付き寄与度」内訳の表示部品（積み上げ1本バー＋凡例）。ルート全体の内訳（RouteAxisProfile）・区間クリック詳細（page.tsx: selectedRouteSegment）の両方から共用する |
| `components/ComparisonPanel/ComparisonPanel.tsx`・`types/experimentSlot.ts`（`ExperimentSlot`型・`MAX_EXPERIMENT_SLOTS`） | 研究モードの実験スロット比較表 |
| `hooks/useAxisCatalog.ts` | `GET /api/axis-catalog`取得。軸一覧・既定重み・ramp軸・軸ラベル・二次軸・ルート色分けモードを一括提供 |
| `services/axisCatalogApi.ts` | 上記フックが叩くbackend APIの薄いラッパー |
| `lib/evaluationAxes.ts` | `PREFERENCE_AXES`（ルート設定・軸別内訳の並び順）・`DEFAULT_ROUTE_PREFERENCE`（route_preference既定値） |
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
              除外する道路（Disclosure折りたたみ）
```

- 軸の一覧・既定重みは`useAxisCatalog`経由（取得完了まで・失敗時は既存軸の静的
  フォールバック）。軸スタジオでの追加が再デプロイなしに反映される。
- カテゴリ（観測/推定/動的）によるグルーピング表示は行わない。軸スタジオは常に
  `category="推定"`固定で軸を作るため、フラットな1本のリストで表示する。
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
  両隣2軸のラベル+%をフロート表示する（`stackBarDragBadge`、ドラッグ終了で消える）——
  native title属性のホバーツールチップ（モバイルでは事実上見えない）の代わり。バーの
  両端付近（累積%が25%未満/75%超）のハンドルは、ラベル併記で幅が増えたバッジが
  パネル外へはみ出すのを避けるため、センター寄せではなく端寄せ（`data-align`属性、
  CSS側で切り替え）で表示する。
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
- 向きコンパス（`WindBearingSlider`）はこのパネルには存在しない。風・勾配の走行方位は
  `page.tsx`の単一共有state（`travelBearingDeg`）を地図上の`TravelBearingControl`
  1箇所からのみ設定する（[ページ全体構成・状態管理](page-composition.md)「動的材料
  （風・勾配）の状態別表現契約」参照）。
- `routePreference`（送信対象）とカタログのキー集合を`syncRoutePreferenceKeys`で
  双方向同期する（軸の追加/unpublishに追従。backendは「上書きするなら既知の全axis_id
  キー一致」を要求するため、ズレるとルート生成が422になる）。
- 除外する道路（0次フィルタ）は`Disclosure`で折りたたみ表示。既定値のまま変えていない
  利用者が大半のため既定で閉じるが、既に変更済みの場合（`hardFilterCustomized`）は
  「変更していることに気づかず開けない」事故を避けるため既定で開く。
- `resetButton`（既定値に戻す）は`routePreference`・`hardFilters`の両方を一括で初期状態へ戻す。

**暗黙の前提**: `useAxisCatalog()`は`page.tsx`と`RouteSettingsPanel.tsx`から同時に呼ばれうる
（`page.tsx`がマウントした時点で子の`RouteSettingsPanel`も同時マウントされるため）。
解決済みのカタログはモジュールレベルの単一ストア（`useSyncExternalStore`）として持ち、
全呼び出し元が同じオブジェクト参照を購読するため、どちらか一方のフェッチが解決すれば
両方の呼び出し元へ即座に反映される（2インスタンス間で`axes`配列が食い違うことは
構造的に起こらない）。同時に飛んでいる（未解決の）フェッチはモジュールレベル変数
`inFlightCatalogFetch`で重複排除する。永続キャッシュはしない（軸スタジオでの公開操作を
再デプロイなしに反映するため、後続の別マウント[モバイルのBottomSheetを開き直す等]では
改めて最新を取得する）が、フェッチ失敗時は共有ストアを書き換えない（他の呼び出し元が
既に取得済みの正常なカタログを、失敗した側の再フェッチが巻き戻すことはない）。

**暗黙の前提（`loaded`フラグの意味）**: `AxisCatalog.loaded`は「取得成功し他フィールドが
実際のDB由来の値であること」を表す。`loaded=false`（未取得/失敗）の間は他フィールドが
ビルド時静的フォールバックの可能性があるため、「軸スタジオの現在の公開軸集合と一致して
いなければならない」処理（`route_preference`のキー整合等）ではこのフラグで未確定状態を
区別しなければならない。取得成功時に軸が0件（全軸非公開）であっても`loaded=true`になる
（0件も確定した実際の状態のため）。

## WindBearingSlider.tsx（走行方位ダイヤル）／TravelBearingControl.tsx（地図上の入口）

外部ライブラリを使わない自前実装のコンパス型UI。中心から伸びる矢印
（`Map/icons.tsx: WindDirectionArrowIcon`）を直接つかんで回すダイヤルで、矢印自体が
指す向きがそのまま値になる。`value`/`onChange`/`ariaLabel`のみを扱う汎用コンポーネントで、
時刻には一切関与しない（時刻は別の共有タイムライン`DynamicLayerTimeSlider`が担当）。

`WindBearingSlider`自体は本コンポーネント表に無い`components/TravelBearingControl/
TravelBearingControl.tsx`（`page.tsx`から直接importされ地図上に置かれるアイコンボタン）
1箇所だけからマウントされる。`page.tsx`の単一共有state`travelBearingDeg`（風・勾配で
共有、[ページ全体構成・状態管理](page-composition.md)「動的材料（風・勾配）の状態別
表現契約」参照）を`TravelBearingControl`が受け取り、地図右上（MapLibreのズーム+/−・
回転コントロールの直下）のアイコンボタンをトリガーにしたRadix Popoverの中で
`WindBearingSlider`を開閉する。表示条件は風・勾配いずれかの環境/評価軸表示が1件でも
ONかつ`!hasDetail`（同ファイルのコメント参照）。

`cardinalLabel(bearingDeg)`（0〜360度→8方位の日本語ラベル）は`backend/app/domain/geo.py:
compass_label`と同じラベル配列・丸めアルゴリズムをfrontend側に持つ。
`WindBearingSlider.test.ts`が既知の入出力ペアでbackendとの一致を検証する。

角度計算・ドラッグ処理は`RouteSettingsPanel.tsx: startBoundaryDrag`（帯グラフの境界
ドラッグ）と同じ「pointerdown起点でwindowへ直接pointermove/upを登録する」パターンを
踏襲する（pointer captureが環境によって確実に効くとは限らないため使わない、という同じ
理由）。ダイヤル自体（矢印の余白を含む円全体）が当たり判定になり、円のどこを触っても
ドラッグを開始できる——特定の小さなノブや細いリングを狙う必要が無い。矢印のタップ位置を
即座に値へ反映する（tap-to-set）ため、ドラッグ開始の初動から値が動く。矢印キー
（`KEY_STEP_DEG`単位）でのキーボード操作にも対応する。`WindBearingSlider.component.test.tsx`
（happy-dom）がキーボード操作・aria属性を検証する——ポインタドラッグの角度計算は
`getBoundingClientRect()`に依存しhappy-domでは実寸を返さないため単体テストで再現できず
（`RouteSettingsPanel.test.tsx`の帯グラフ境界ドラッグと同じ制約）、Browserペインでの
目視確認で別途検証する。

## RouteAxisProfile.tsx（候補ごとタブの中身: 地図色分け＋軸別内訳）

page.tsx（[ページ全体構成・状態管理](page-composition.md)参照）が組み立てる候補ごとの
タブ（方向・距離のみを表示。総合難易度の点数はタブ内では繰り返さない）の中身として、
候補1件につき1つ表示する。呼び出し側（page.tsx）は`axes`をルート設定の重み>0の軸のみへ
絞り込んで渡す。

- **地図の色分けチップ**: 「総合難易度」＋渡された各軸のうち**地図の色分けに対応する軸だけ**
  （`routeStyleModes.some(mode => mode.id === axis.axisId)`で判定。公開軸は無条件で
  地図の色分けモードを持つため、この判定は実質的に「重み>0の公開軸すべて」を通す）を、
  `RouteSettingsPanel.module.css`の`legendChip`/`legendDot`/`chipRow`クラスをそのまま
  importして流用した1行の折り返しチップ列（`RouteSettingsPanel`の軸チップ列と同じ見た目）で
  表示する。1チップは「色ドット＋ラベル（クリックで選択）」「(i)説明文ポップオーバー
  （`axis.description`、`legendInfoButton`/`legendInfoPopover`を流用）」「地図色分けアイコン
  （`legendMapColorButton`を流用、`MapAppearanceIcon`）」の3要素——`RouteSettingsPanel`の
  軸チップと見た目は同じだが、地図色分けアイコンの役割は異なる。`RouteSettingsPanel`側は
  `layerVisibility`のON/OFF（視界内の全道路の背景色分け）を切り替えるが、こちらはルート
  確定後（`page.tsx`: `showWindAxis = layerVisibility.windAxis && !hasDetail`等により評価軸
  グループの背景表示自体が無効化される）の画面のため、独立した背景レイヤーは持たない。
  クリックするとトグルボタンと同じ`onSelect`（このチップを選択＝選択中ルートをこの軸で
  色分け）を呼ぶ——レイアウトの見た目だけを揃え、実際の切り替えは常にルート線の色分けへ
  一本化している。「総合難易度」チップは軸固有の説明・地図レイヤーを持たないため、
  (i)アイコン・地図色分けアイコンいずれも出さない（`description`未指定時は非表示、
  `AxisChip`の`description`プロパティ参照）。選択状態は`routeStyleModeId`
  （`Map/routeStyleModes.ts`）でpage.tsx側が管理し、地図上の色分け式を切り替える。
  チップ選択時、地図上の「ルート」チップ（`layerVisibility.route`）がまだOFFなら自動で
  ONにする。地図の色分け対象を選ぶ役割はこのチップ列だけが持ち、下記の軸別内訳は選択状態を
  持たない読み取り専用の一覧（`axis_contributions`にキーが無い軸[色分けに対応しない軸を
  含む]は表示されない）。このチップ列に並ぶチップは常にクリック可能（`AxisChip`は非活性
  描画を持たない）——色分けに対応しない軸をこの列へ含めない絞り込みが、その前提を
  成立させている。
- **総合難易度**: `RouteCandidate.overall_difficulty`（絶対基準0-100の軸重み付き合成値）を
  表示する。下記内訳の合計そのものであり、内訳の1項目としては扱わない。候補タブの並び順
  もこの値の昇順（backend `route_generator.py`が返す`routes`配列の並び順をそのまま使う、
  [ページ全体構成・状態管理](page-composition.md)参照）。説明文言はこのコンポーネント
  自身は持たず、呼び出し元（`app/page.tsx`の「ルート結果」見出し脇の
  `renderRouteResultHeaderActions()`が返す`FieldLabel`、候補タブすべてに共通の1箇所）へ
  集約している。
- **軸別内訳（重み付き寄与度）**: `RouteCandidate.axis_contributions`（axis_id→重み付き
  寄与度0-100、backend側で区間ごとの合成に使ったのと同じ重み配分を軸別に分解しルート
  全体へ距離加重平均で集約した値。評価できなかった軸はキー自体が無く非表示。backend:
  `domain/evaluation.py: compose_costs_from_axis_matrix`参照）を、「総合難易度」の数字の
  隣に`AxisContributionBar`（積み上げ1本バー＋その下の凡例）でそのまま表示する。合計が
  丸め誤差を除いて`overall_difficulty`と数学的に一致するため、frontend側での独自の
  重み計算は行わない。バーの各セグメントの色は`axisColors`（地図色分けチップと同じ配色）、
  幅は寄与度の値そのもの。
- **凡例の表示設定**: `stackBarLegendTrigger`パターン（見出し脇の(i)アイコン→ポップオーバー
  でチェックボックス一覧）で、選択中モードの凡例カテゴリを地図上で表示/非表示できる。

## AxisContributionBar.tsx（「重み付き寄与度」の共有表示部品）

`RouteSettingsPanel.module.css`の`stackBar`/`stackSegment`クラス（「重み配分」帯グラフと
同じ表現）をそのまま流用した積み上げ1本バーと、その下の凡例（色ドット＋ラベル＋数値）を
描画する。`axes`（表示順・ラベル）・`contributions`（axis_id→寄与度）・`axisColors`のみを
受け取る汎用コンポーネントで、値の出どころ（ルート全体か特定の区間か）を一切知らない。
`contributions`にキーが無い軸は自動的に除外されるため、呼び出し側は`axes`を絞り込まずに
渡してよい。ルート全体の内訳（RouteAxisProfile、`RouteCandidate.axis_contributions`）と
区間クリック詳細（page.tsx、`RouteSegmentDetail.axis_contributions`、下記「区間クリック
詳細（selectedRouteSegment）」参照）の両方が同じこのコンポーネントを使う——「重み付き
寄与度」の表示はこの1部品に一元化されており、値の出どころごとに別の表現を持たない。

## 区間クリック詳細（selectedRouteSegment）

地図上でルート線の区間をクリックすると、`page.tsx`の`selectedRouteSegment` state
（`{ segment: RouteSegmentDetail, latitude, longitude }`、`MapView.tsx:
handleRouteSegmentClick`がクリック地点の座標とともに設定する）が入る。地図側は
クリック地点へ軽量なマーカーを立てるだけでテキストポップアップは出さない
（[地図: 静的レイヤー・道路表示](static-map-layers.md)参照）。`selectedRouteSegment`が
non-nullの間、「ルート結果」タブはルート全体の内訳の代わりにその区間の地点・到達予想
時刻＋`AxisContributionBar`（区間の`axis_contributions`）を表示し、×ボタンで
`selectedRouteSegment`をnullへ戻すとルート全体表示に復帰する。

## ComparisonPanel.tsx

- 研究モードの実験スロット比較表。表示順は
  (1) 生の物理量（距離・獲得標高・風スコア・舗装率。単位・意味がaxis_difficultiesとは
  異なる別系統のフィールドのため区別して残す）→
  (2) 個別軸の生値行（`axisLabels`・`axes`をpage.tsxから受け取り、
  `RouteCandidate.axis_difficulties`から動的生成。軸スタジオの軸増減に自動追従する）→
  (3) 全軸合成の総合難易度（`overall_difficulty`、末尾固定）。各列は各回の
  `ExperimentSlot.topCandidate`（生成直後の`overall_difficulty`最小候補で固定、
  [ページ全体構成・状態管理](page-composition.md)参照）。page.tsxが渡す`axes`は、
  表示中のいずれかの実験スロットで生成時点の重み（`ExperimentSlot.conditions.
  route_preference`）が>0だった軸に絞り込み済み——現在のライブな`routePreference`
  （「今」の設定）は使わない。

## RouteForm.tsx

距離入力・候補件数入力・巡航速度入力・生成ボタン。`RouteMode`（"loop"|"destination"）で
周回/目的地モードを切り替える。モバイル上部バー向けの`compact`表示を持つ。目的地モードでは
距離入力を出さない。巡航速度（km/h、backend `RouteGenerateRequest.assumed_speed_kmh`、
範囲・既定値は`route-generate-config.json`の`min/max/default_assumed_speed_kmh`）は
全モードで表示し、範囲外・空欄は送信前にエラーにする。候補件数入力は経由地が無い場合のみ表示する（経由地を伴う目的地ルートはbackendが
候補件数を常に1件へ固定し無視するため、`maxRoutesRelevant`＝`routeMode==="loop"||
waypointCount===0`で表示・検証の両方を揃える）。経由地・目的地のいずれも未指定のまま
生成しようとするとサイレント失敗せずエラー文言を出す。

距離・候補件数・巡航速度いずれの`<Input type="number">`もネイティブのスピンボタン（上下矢印）をCSS
（`[&::-webkit-inner-spin-button]:appearance-none`等）で非表示にする——直接入力が主な
操作手段で、矢印クリックは想定していないため。`inputMode="numeric"`でモバイルの
数値専用キーボードを明示し、`onFocus`で既存の値を全選択して毎回消してから打ち直す手間を
無くす。`distance`・`maxRoutes`・`assumedSpeed`はいずれもstring stateのまま親（`page.tsx`）が持ち、
数値への変換は送信直前（`handleSubmit`内の検証）でのみ行うため、`AxisComposer.tsx`の
`NumberField`（[軸スタジオ](axis-studio.md)参照）が対処する「入力途中でReactの制御値が
NaNへ倒れる」問題はこの入力には無い。候補件数の上限・既定値は
`types/generated/route-generate-config.json`の`max_routes`/`default_max_routes`
（backend: `RouteGenerateRequest.max_routes`のFieldメタデータから生成）から導出し、
1〜上限の整数以外はエラー表示で送信を止める。
