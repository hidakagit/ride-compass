# ルート設定・結果パネル（frontend）

## 責務

一般ユーザー向けのルート生成条件入力（距離・重み・除外道路）と、生成結果の表示・比較
（軸別内訳・候補一覧・研究モードの実験スロット比較）を担う。

**対象ファイル**

| ファイル | 責務 |
|---|---|
| `components/RouteForm/RouteForm.tsx` | 距離スライダー・候補数ステッパー・周回/目的地モード切替の入力欄。「ルート設定」区分の「生成条件」「重みづけ」2タブもホストする（下記参照） |
| `components/RouteForm/useRouteFormSubmit.ts` | 上記の検証・送信ロジック（`{error, handleSubmit}`）。「ルート生成」ボタン自体は`RouteForm`の外（`page.tsx`の見出し行）にあるため分離している（下記参照） |
| `components/RouteSettingsPanel/RouteSettingsPanel.tsx` | 一般向け軸重み設定・除外道路（地図の色分けはここになく`LensControl`のみが持つ、下記参照） |
| `components/WindBearingSlider/WindBearingSlider.tsx` | 走行方位の指定コンパスダイヤル（`TravelBearingControl`から使われる。単体としての設置場所は[ページ全体構成・状態管理](page-composition.md)参照） |
| `components/RouteAxisProfile/RouteAxisProfile.tsx` | 候補ごとのタブの中身（公開軸すべての軸別難易度一覧＋「重み付き寄与度」内訳）。地図の色分けを選ぶ操作はここには無い（`LensControl`）。候補一覧のタブ自体はpage.tsxが直接組み立てる（[ページ全体構成・状態管理](page-composition.md)参照） |
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
  移し替え）                                (i)説明文ポップオーバー
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
  情報アイコン（`stackBarLegendTrigger`）を押すと、操作説明（帯の境界をドラッグして
  配分を調整できる旨）に続けて全軸ぶんの色ドット+ラベル+現在の%を一覧するポップオーバーが
  開く（見出し自体は「重み配分」の短い表記のみ）。境界をドラッグしている間だけ、そのハンドルの直上に
  両隣2軸のラベル+%をフロート表示する（`stackBarDragBadge`、ドラッグ終了で消える）——
  native title属性のホバーツールチップ（モバイルでは事実上見えない）の代わり。バーの
  両端付近（累積%が25%未満/75%超）のハンドルは、ラベル併記で幅が増えたバッジが
  パネル外へはみ出すのを避けるため、センター寄せではなく端寄せ（`data-align`属性、
  CSS側で切り替え）で表示する。
- 軸の凡例チップ（`renderLegendChip`）は「色ドット+ラベル（タップで有効/無効を
  切替、weight>0が有効の判定基準）」「(i)説明文ポップオーバー」の2要素で構成される
  複合ボタン群。無効な軸（weight=0）はチップ全体を半透明にする。`route_preference`の
  重みを切り替えるだけで、地図の色分けとは無関係（地図の色分け（レンズ）はこのパネルには
  なく、地図上の`LensControl`だけが持つ）。
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
時刻には一切関与しない（時刻は条件バー`RideConditionBar`の出発時刻が担当）。

`WindBearingSlider`自体は本コンポーネント表に無い`components/TravelBearingControl/
TravelBearingControl.tsx`（`page.tsx`から直接importされ地図上に置かれるアイコンボタン）
1箇所だけからマウントされる。`page.tsx`の単一共有state`travelBearingDeg`（風・勾配で
共有、[ページ全体構成・状態管理](page-composition.md)「動的材料（風・勾配）の状態別
表現契約」参照）を`TravelBearingControl`が受け取り、地図右上（MapLibreのズーム+/−・
回転コントロールの直下）のアイコンボタンをトリガーにしたRadix Popoverの中で
`WindBearingSlider`を開閉する。出発時刻・想定速度と同じ走行条件の一部として常時表示する
（風・勾配の表示状態に依存しない）。

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

- **軸別難易度の一覧**: 公開軸すべて（軸カタログ順）を「色ドット＋ラベル＋(i)説明＋難易度
  （`RouteCandidate.axis_difficulties`、四捨五入）」の行で並べる。この候補を評価した重み
  （生成時点の`route_preference`）が0の軸は「未使用」バッジ付きで薄く残し、値が無い軸は
  「データなし」を示す。選択操作は持たない（地図の色分けは`LensControl`）。
- **負荷（難易度×距離）**: `RouteCandidate.difficulty_load`を総合難易度の隣へ併記する
  （(i)で意味を説明する）。総合難易度が距離で正規化された平均であるのに対しこちらは総量で、
  「難所を通っても短いルート」と「遠回りで易しいルート」を見比べるための値
  （[評価・スコアリング](../backend/evaluation-scoring.md)「ルート単位の集約」節参照）。
  候補の並び順には影響しない。
- **総合難易度**: `RouteCandidate.overall_difficulty`（絶対基準0-100の軸重み付き合成値）を
  表示する。下記内訳の合計そのものであり、内訳の1項目としては扱わない。候補タブの並び順
  もこの値の昇順（backend `route_generator.py`が返す`routes`配列の並び順をそのまま使う、
  [ページ全体構成・状態管理](page-composition.md)参照）。数字の隣に(i)説明ポップオーバー
  （このコンポーネント自身が持つ、負荷の説明と同じ形）を置く。
- **軸別内訳（重み付き寄与度）**: `RouteCandidate.axis_contributions`（axis_id→重み付き
  寄与度0-100、backend側で区間ごとの合成に使ったのと同じ重み配分を軸別に分解しルート
  全体へ距離加重平均で集約した値。評価できなかった軸（データ欠損）はキー自体が無く非表示。
  重み0の軸はキー自体は残り値が常に0.0になる（backend:
  `domain/evaluation.py: compose_costs_from_axis_matrix`参照。frontend側で値0を除外する、
  下記`AxisContributionBar.tsx`参照）を、「総合難易度」の数字の
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
`contributions`にキーが無い軸・値が0の軸（重み0の軸は常にこの値になる）は自動的に
除外されるため、呼び出し側は`axes`を絞り込まずに渡してよい。
ルート全体の内訳（RouteAxisProfile、`RouteCandidate.axis_contributions`）と
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
`selectedRouteSegment`をnullへ戻すとルート全体表示に復帰する。研究モード
（`researchEnabled`）の間だけ、`AxisContributionBar`の下へ区間の材料値
（`RouteSegmentDetail.material_values`）の一覧を追加表示する——一般ユーザー向けには
出さない（走行中のスマホ利用が主で情報量を増やしたくないという方針、ComparisonPanel.tsxの
材料値行と同じ`lib/axisMaterialsCatalog.ts: materialCatalogLabel`/`formatMaterialValue`を使う）。

## ComparisonPanel.tsx

- 研究モードの実験スロット比較表。表示順は
  (1) ルート属性（距離・獲得標高。材料ではないため`material_values`には乗らない固定行）→
  (2) 材料値の生値行（`RouteCandidate.material_values`から動的生成。重み>0の軸が参照する
  材料id→値の辞書で、いずれかのスロットが値を持つ材料だけを行にする。ラベル・単位は
  `materials`[page.tsxが`useMaterialCatalog()`を渡す]から引く、
  `lib/axisMaterialsCatalog.ts: materialCatalogLabel`/`formatMaterialValue`共用）→
  (3) 個別軸の生値行（`axisLabels`・`axes`をpage.tsxから受け取り、
  `RouteCandidate.axis_difficulties`から動的生成。軸スタジオの軸増減に自動追従する）→
  (4) 全軸合成の総合難易度（`overall_difficulty`、末尾固定）。各列は各回の
  `ExperimentSlot.topCandidate`（生成直後の`overall_difficulty`最小候補で固定、
  [ページ全体構成・状態管理](page-composition.md)参照）。page.tsxが渡す`axes`は、
  表示中のいずれかの実験スロットで生成時点の重み（`ExperimentSlot.conditions.
  route_preference`）が>0だった軸に絞り込み済み——現在のライブな`routePreference`
  （「今」の設定）は使わない。旧・風スコア/舗装率の固定行（`RouteCandidate.wind_score`/
  `road_score`直接参照）は材料値の生値行へ置き換えた。

## RouteForm.tsx・useRouteFormSubmit.ts

`RouteMode`（"loop"|"destination"）で周回/目的地モードを切り替える入力欄一式
（`RouteForm.tsx`）と、その検証・送信ロジック（`useRouteFormSubmit.ts`）を分離する。
デスクトップ・モバイルとも「ルート設定」区分（`RouteSettingsPanel`と同じ場所）から呼ぶ。

「ルート設定」区分自体を「生成条件」（`RouteForm`のモード切替・距離・候補数）と
「重みづけ」（`weightsPanel`propで受け取る`RouteSettingsPanel`一式）の2タブへ分け、
`Tabs.Root`（`@radix-ui/react-tabs`）で`RouteForm`自身がホストする。両タブとも
`forceMount`で常時マウントし表示だけ`data-state`で切り替える（`RouteSettingsPanel`が
ローカルstate[`lastWeights`等]を持つため、タブ切替のたびにアンマウントすると失われる。
page.module.cssの`.outcomeTabPanel`と同じ方式）。「ルート生成」ボタン・検証エラー表示は
`RouteForm`の外（`page.tsx`の「ルート設定」見出し行、デスクトップは`Disclosure`の
`trailing`・モバイルは`BottomSheet`の`headerAction`、「ルート結果」見出し行の
`renderRouteResultHeaderActions`と同じ場所）に置き、どちらのタブを見ていても押せる
（`page.tsx: renderRouteSectionHeaderActions`）。検証・送信ロジック自体は
`useRouteFormSubmit`（`distance`・`maxRoutes`・`routeMode`・`waypointCount`・
`destinationState`・`onGenerate`を受け取り`{error, handleSubmit}`を返す）へ切り出し、
`page.tsx`がヘッダーのボタンから直接呼ぶ。`isMaxRoutesRelevant(routeMode, waypointCount)`
は`RouteForm`（候補数ステッパーの表示要否）・`useRouteFormSubmit`（検証要否）の両方が
参照する単一の情報源。

距離は`<input type="range">`のスライダー、候補数は「‹ 8 › 件」のステッパー
（-/+ボタン、`DynamicLayerTimeSlider`の1コマ送りボタンと同じ役割分担）にし、
数値の直接入力欄は持たない（原則としてユーザーに数字を直接入力させない方針）。
distance・maxRoutesはいずれもstring stateのまま親（`page.tsx`）が
持ち、数値への変換は送信直前（`useRouteFormSubmit: handleSubmit`内の検証）でのみ行う。
スライダー・ステッパーはmin/maxで値域を強制するため空文字・範囲外を作れず、
`useRouteFormSubmit`側の距離・候補数の範囲検証は主に目的地モード（経由地を伴うと
候補数ステッパー自体が非表示になり、その間もstring stateとして残り続ける値に対する
境界チェック）向けに残っている。目的地モードでは距離入力を出さない。想定速度はこの
フォームでは扱わない（地図右上の条件アイコン列`RideConditionBar`、page-composition.md参照）。
候補数ステッパーは経由地が無い場合のみ表示する（経由地を伴う目的地ルートはbackendが
候補件数を常に1件へ固定し無視するため）。経由地・目的地のいずれも未指定のまま
生成しようとするとサイレント失敗せずエラー文言を出す。

目的地モードへ切り替えた時点で目的地・経由地とも未指定なら、ゴールアイコンを押さなくても
即座に地図タップで目的地を指定できる状態（armed）にする（`page.tsx:
handleRouteModeChange`）。既に目的地・経由地がある場合は自動武装しない——次のタップの
意図が「経由地の追加」である可能性があり、武装したままだと意図せず目的地が上書きされて
しまうため。
