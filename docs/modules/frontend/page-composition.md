# ページ全体構成・状態管理（frontend）

## 責務

`app/page.tsx`がアプリのコンポジションルート兼状態ハブ。地図（`MapView`）・ルート設定/
結果パネル（`RouteSettingsPanel`・`RouteForm`・`RouteAxisProfile`）・地図
オーバーレイ制御（`MapOverlayControls`・`MapLayersPanel`）・研究モードの比較表
（`ComparisonPanel`）を1つのReactツリーへ束ね、状態を集約する。Next.jsのApp Router
フレームワークファイル（レイアウト・エラーバウンダリ）と、特定の機能モジュールに
属さない横断的なlib/hooks/UI基盤もここで扱う。

**対象ファイル**

| レイヤー | ファイル |
|---|---|
| app | `page.tsx`・`layout.tsx`・`error.tsx`・`global-error.tsx` |
| services | `routeApi.ts`（ルート生成・プレビューAPI） |
| hooks | `useStoredState.ts`・`useIsMobile.ts`・`useElementHeightCssVar.ts`・`useLocation.ts`・`useDebouncedValue.ts`・`useIsomorphicLayoutEffect.ts` |
| lib | `apiBaseUrl.ts`・`apiError.ts`・`backendInternalUrl.ts`・`fetchJson.ts`・`apiTimeouts.ts`（APIリクエストのタイムアウト。呼び出しの性質ごとの名前付き定数）・`cn.ts`・`safeStorage.ts`（localStorageの読み書きで例外を外へ出さない薄いラッパ）・`generationRequest.ts`（生成リクエストのpayloadと`conditionsDirty`の比較キーを同じ入力から導出する純関数）・`routeSplice.ts`（候補どうしが別々の道を通る区間を`edge_ids`の集合演算で求め、表示中の側と相手側を対応づけ、選んだ区間を差し替えた経路を組み立て、合成結果を生成候補と同じ並び順の規約［`overall_difficulty`昇順、最短経路は先頭固定］へ差し込む純関数。差し替えた経路の評価はbackendが行うため計算式は持たない。**並び順の規約はbackendにもある**——backendは合成結果を1件しか返さず他候補を知らないため差し込む位置をここで決めるしかなく、片方を変えたらもう片方も変える。[T621](../../tasks/T621.md)） |
| types | `types/route.ts`（`RouteCandidate`等の生成APIレスポンス型） |
| components/Map | `useLayerDataStatus.ts`（`layerDataStatus` stateの実装） |
| components/ui | `Button/Button.tsx`・`Card/Card.tsx`・`Checkbox/Checkbox.tsx`・`Dialog/Dialog.tsx`・`Input/Input.tsx`（汎用UI基盤、全モジュール共通）・`adminPanel.module.css`（管理画面パネルが共有する外枠スタイル）・`roundIconButton.module.css`（地図に重ねる小さい丸アイコンボタン）・`stepperButton.module.css`（値を1段ずつ増減する枠線ボタン）・`floatingPopover.module.css`（情報アイコンから開く浮きパネル）・`infoButton.module.css`（見出し脇の(i)トリガー）・`mapCtrlButton.module.css`（MapLibre純正コントロールの続きに見える29px四方ボタン）・`statusDot.module.css`（データ取得状態の3表現）・`axisLegend.module.css`（軸の寄与を示す帯グラフと凡例ドット）・`unusedBadge.module.css`（重み0の軸に添える「未使用」バッジ）。いずれも各CSS Modulesから`composes`で参照する共有スタイル |
| components（特定モジュールの責務ではない共通部品） | `ErrorText/ErrorText.tsx`（フォームのエラー文言表示）・`BottomSheet/BottomSheet.tsx`（モバイル下部シート、下記「モバイル/デスクトップのレイアウト分岐」節参照）・`Disclosure/Disclosure.tsx`（折りたたみ表示、[ルート設定・結果パネル](route-settings-and-results.md)等が使う） |
| components/RideConditionBar | `RideConditionBar.tsx`（地図右上、走行方位アイコン直下の走行条件アイコン列本体。出発時刻・想定速度ともTravelBearingControlと同じ29px四方のアイコンボタンで、タップしたポップオーバー内はドラッグ式タイムライン＋`input[type=datetime-local]`の直接指定[出発時刻]、スライダー＋数値入力[想定速度]）・`departureTimeline.ts`（出発時刻ポップオーバーのドラッグタイムライン用の目盛り生成。気象レイヤーの実フレームには依存しない自己完結した合成タイムライン） |
| components/DynamicLayerTimeSlider | `DynamicLayerTimeSlider.tsx`（ドラッグ/横スクロールで時刻を選ぶ汎用タイムラインUI。`RideConditionBar`が出発時刻ピッカーとして使う唯一の呼び出し元） |

`apiBaseUrl.ts`/`backendInternalUrl.ts`はブラウザからのfetch先（`NEXT_PUBLIC_API_BASE_
URL`）とNext.js route handlerからのサーバー間fetch先を区別する（後者はコンテナ内部
ネットワークのURLになりうるため別変数）。`useLocation.ts`はブラウザのGeolocation APIを
扱うhookで、起点座標の取得に使う。

タイムアウトは`apiTimeouts.ts`の名前付き定数（既定15秒・状態確認5秒・カタログ10秒・
分布プレビュー60秒・管理画面の重い集計90秒）から選ぶ。**同じ呼び出しのブラウザ側
クライアントとNext.js route handler（backendへの転送）は必ず同じ定数を共有する**
——別々に持つと片方だけ延ばしてももう片方が先に打ち切って症状が変わらない。

`fetchJson.ts`/`apiError.ts`は全`services/*Api.ts`クライアントが共有するfetch骨格と
エラー正規化。骨格は「fetch→通信エラーのtry/catch→`response.ok`確認→エラーボディ解析→
`ApiError`をthrow→各段階でdebugLog記録」の7段で、**呼び出しごとに違うのは
メソッド・成功時のボディ解釈・エラー文言の3点だけ**:

| 入口 | 戻り値 | 使う場面 |
|---|---|---|
| `requestJson<T>` | 応答をJSONとして解釈（204は`undefined`） | 大半のクライアント |
| `requestOk` | 成功時の`Response`そのもの（成功ログは呼び出し側） | 成功ログのfieldsが呼び出しごとに違う場合 |
| `fetchJson<T>` | `requestJson`のGET向け糖衣 | 文言を`errorLabel`から「◯◯の取得/解析に失敗しました」で組み立てる |

`ApiError`は`x-request-id`とHTTPステータスを**属性として**持ち、`message`には入れない。
リクエストIDは開発者向け（debugLog・`BackendLogsPanel`）の情報で、画面へ出す文言に混ぜると
利用者に意味が無いまま長くなり、狭い幅のレイアウト（常設ヘッダー）を溢れさせる。

**暗黙の前提**: 骨格を各クライアントへ写経すると、片方だけ改良された非対称が静かに生まれる
（タイムアウト判別と`error.cause`のログがPOST系1箇所にしか無い状態が実際に生まれていた）。
通信エラー時に元のErrorをそのまま投げるか`messages.failure`で包み直すかだけは
`wrapNetworkError`で選ぶ——例外のmessageをそのまま画面へ出す呼び出し元
（`BackendLogsPanel`）だけが包む側を使う。

## 主な構成要素（import元）

| 種別 | コンポーネント |
|---|---|
| 地図本体 | `Map/MapView`（全静的/動的レイヤーのMapLibre実装本体） |
| 地図オーバーレイ制御 | `MapOverlayControls`（地図上チップ）・`MapLayersPanel`（サイドバー）・`TravelBearingControl`（走行方位ダイヤルの地図右上アイコン）・`LensControl`（地図上部中央のレンズ選択ピル）・`RideConditionBar`（走行方位アイコン直下、地図右上の走行条件アイコン列、出発時刻・想定速度） |
| ルート設定 | `RouteForm`（モード切替/距離/候補件数/生成ボタン）・`RouteSettingsPanel`（0次除外・軸選択・重み） |
| ルート結果 | `RouteAxisProfile`（候補ごとのタブの中身、軸別難易度）。候補ごとのタブ自体は独立コンポーネントを持たずpage.tsxが直接組み立てる |
| 研究モード | `ComparisonPanel`（実験スロット比較表） |
| レイアウト | `BottomSheet`（モバイル下部シート） |

## page.tsxの状態管理

stateは`page.tsx`の`useState`に集約し、子コンポーネントへはpropsで渡す（子が独自に
同じ状態を持たない）。全件の一覧は`page.tsx`を読むのが正で、ここでは**永続化するかどうかの
判断基準**だけを示す——一覧を書き写すと、stateを1つ足したときにこの節だけが古くなる。

| 永続化 | 判断基準 | 代表例 |
|---|---|---|
| `localStorage` | 利用者が自分で決めた設定で、次に開いたときも同じであってほしいもの | 評価の設定（`routePreference`・`hardFilters`）、レイヤー表示（`layerVisibility`・`lens`）、パネル開閉 |
| なし | そのセッション限りの結果・一時的な入力・地図の見え方 | 生成結果（`routes`・`selectedRouteId`）、目的地モードの入力、地図ビューポート、データ取得状態 |

復元時の注意が要るのは、**正本がbackend側にある設定**だけである。`hardFilters`は
`lib/hardFilterSync.ts: syncHardFilterKeys`が、保存済みの値を正本
（`routeGenerateConfig.hard_filters`）のキー集合へ整合させてから使う——キー集合の完全一致を
要求するAPIのため、フィルタが増減した後の古い保存値をそのまま送ると全リクエストが422になる。

## 動的材料（風・勾配）の状態別表現契約

`page.tsx`は風・勾配それぞれについて「環境グループ（面塗り、探索用）」と「評価軸グループ
（線、視界内の全道路へ一律色分け）」の2表現を同時に配線する。両者は`[時刻, 向き]`のうち
「時刻」の扱いが異なる（風のみ時刻依存）が、「向き」は単一の共有state
`travelBearingDeg`を風・勾配の両方が使う（走行方位という1つの概念を表す単一state）:

```
travelBearingDeg（page.tsxの単一useState、TravelBearingControlで操作）。出発時刻は`useDynamicWeatherLayers`の`dynamicLayerTargetTime`、想定速度は`assumedSpeedKmh`（いずれも地図右上の条件アイコン列`components/RideConditionBar/RideConditionBar.tsx`で操作し、生成リクエストの`start_time`/`assumed_speed_kmh`とレンズの`speed_kmh`へ同じ値が乗る）
  │
  ├─→ 風:   [時刻]dynamicLayerTargetTime（useDynamicWeatherLayers由来）
  │           │
  │           ├─→ 環境: 矢印のみ（showWindVector = layerVisibility.windVector）。走行方位に
  │           │     依存する面塗りは持たない（[地図: 動的気象レイヤー](dynamic-weather-layers.md)参照）
  │           └─→ 評価軸（線）: レンズがその軸を指している間だけ（下記の共通経路）
  │
  └─→ 勾配: （時刻非依存）
              │
              ├─→ 環境（面）: showGradientFill = layerVisibility.gradientFill && !hasDetail
              │     gradientGridCellsFromTileResponses(勾配軸のbyTile)
              └─→ 評価軸（線）: レンズがその軸を指している間だけ（下記の共通経路）

  評価軸（線）の共通経路（軸ごとの分岐を持たない）:
    dedicatedFetchAxes = [レンズが指す専用way値配信軸（lensBackgroundShown中）]
                       ∪ [showGradientFillなら勾配軸]
    useDedicatedWayValues(dedicatedFetchAxes, mapViewport, travelBearingDeg,
                          dynamicLayerTargetTime, assumedSpeedKmh)
      → 時刻・想定速度は軸カタログのneedsTime/needsSpeedが立つ軸のリクエストにだけ載る
    dedicatedWayValueVisibility = レイヤーID（`${axisId}Axis`）→ lens === axisId && lensBackgroundShown
```

**ルート確定後（`hasDetail`）**、環境グループの面表示は終了する（`showGradientFill`が
`!hasDetail`を含む）。評価軸グループの一律色分けは**`lensKeepAfterRoute`（既定ON）次第**で、
ONの間はルート線の色分けと併せて周囲の道路も薄く塗り続ける（`lensBackgroundShown =
!hasDetail || lensKeepAfterRoute`）。ルート線側の色分けは`routeStyleModes.ts`由来のモード
選択が担う。

走行方位の設定UIは`TravelBearingControl`（地図右上、MapLibreのズーム+/−・回転コントロールの
直下に置くアイコンボタン）1箇所へ集約されており、出発時刻・想定速度と同じ「走行条件」の
一部として**常時表示する**（表示条件を持たない）。中身は`RouteSettingsPanel`と同じ
`WindBearingSlider`ダイヤルをRadix Popoverで開く。

**暗黙の前提**: way_id単位の実データ本体（`dedicatedWayValues: ReadonlyMap<axisId,
ReadonlyMap<wayId, value>>`）・フェッチ進行中フラグ（`dedicatedWayValueLoading:
ReadonlyMap<axisId, boolean>`）・表示宣言（`dedicatedWayValueDisplays:
ReadonlyMap<axisId, DedicatedWayValueDisplay>`）は、いずれも`MapView.tsx`の`MapViewProps`上で
軸id→値の1つの汎用propにまとまっている（design-principles.md構造仕様3「軸ごとにpropを
新設しない」）。`page.tsx`が`axisCatalog.dedicatedAxes`（軸カタログから抽出済みの
専用way値配信軸一覧）を横断して構築するため、`dedicated_way_value_layer`軸が増えても
これらのprop自体の変更は不要。一方`gradientFillGeojson`（タイル単位に集計済みの環境グループgridFill本体）は
勾配専用の個別propのまま残っている——風は独立した空間フィールドを持たずgridFill表現自体を
持たないため（[map-axis-coloring.md](map-axis-coloring.md)「gradientGridFill.ts」節参照）、
風・勾配で対称な汎用化の対象にならない。

## 状態の永続化（`hooks/useStoredState.ts`）

`useStoredState(key, defaultValue, {serialize, deserialize, autoSave, reloadKey})`が
localStorageへの保存・復元を1箇所に集約する。

- 復元は`useState`の初期化子ではなく、マウント後の`layout effect`
  （`useIsomorphicLayoutEffect`）で行う（SSR時のHTMLとハイドレーション結果のずれ防止）。
- 保存は「setter呼び出しのたびに即書き込む」方式（`autoSave`省略時true）。
- `reloadKey`: 復元処理を再実行させたい追加の依存値。`deserialize`はrefへ退避しない
  （`reloadKey`が変わった際、その時点の最新の`deserialize`クロージャで再復元する）。例:
  `layerVisibility`は`axisCatalog.loaded`を`reloadKey`にする。キー集合自体は
  `DEFAULT_LAYER_VISIBILITY`固定でカタログに依存しないが、1回目の復元が書き戻した
  移行後の値を2回目の復元がそのまま読み直せるよう揃えている（`page.tsx`の同箇所の
  コメント参照）。レンズの選択（`lens`）は`deserialize`が実行時カタログの
  `routeStyleModes`を参照するため、こちらは2段階復元が意味を持つ。
- `useStoredJsonState`は`JSON.stringify`/`JSON.parse`を既定にした薄いラッパー
  （`/admin`とのstate共有に使う）。
- 読み書きの失敗（プライベートブラウジング等）はデフォルト値へのフォールバックとして
  握りつぶす。

保存する／しないの線引きは「その場で決まる値かどうか」で引く。出発地点・距離・目的地は
毎回初期化し、ルート設定パネルが操作する評価の設定（重み・0次除外）は保存する——同じ
パネルに並ぶ設定の片方だけが消えると、利用者は何が残るかを予測できない。

Reactの外（モジュール評価時に初期値を決めるシングルトン。`lib/debugLog.ts`・
`lib/researchMode.ts`）は`useStoredState`を使えないため、`lib/safeStorage.ts`の
`readStoredValue`/`writeStoredValue`を通す。サイトデータを全面ブロックした環境では
`getItem`/`setItem`ではなく`window.localStorage`のゲッター自体がSecurityErrorを投げ、
モジュール評価時にこれを浴びると例外を受け止める場所が無く、そのモジュールを読む
ページ全体が描画されない。

## page.tsxが橋渡しする主なデータフロー

- `routePreference`（`RouteSettingsPanel`が編集）→ `syncRoutePreferenceKeys`による
  キー整合補正 → ルート生成リクエスト。整合補正は`RouteSettingsPanel`のマウント時
  （`useEffect`）と、`handleGenerate`内（送信直前、パネル未マウント経路の穴埋め）の
  2箇所で行う。
- `layerVisibility`（`MapOverlayControls`/`MapLayersPanel`が共有）→ `MapView`の
  一次属性・気象・スポットの表示制御。
- `lens`（レンズ、`LensControl`が唯一の入口）→ 全道路の塗りは`axisVisibility`（ramp軸）と
  `dedicatedWayValueVisibility`（専用way値配信軸）、ルート線は`MapView`の`routeStyleModeId`
  へ、いずれも同じ1つの値から導出する（どちらもレイヤーID→booleanの汎用Recordで、軸ごとの
  propを持たない。[地図: 軸・ルート色分け](map-axis-coloring.md)参照）。
- `RAMP_AXES`/`axisCatalog.rampAxes`・`DEDICATED_WAY_VALUE_AXES`/`axisCatalog.dedicatedAxes`
  → `buildMapLayers`/`buildStaticFilterAxes`/`buildRoadSurfaceSharedLayerIds`経由で
  レイヤー構成を組み立てる。
- `axisCatalog.secondaryAxes`（`primaryAttributeIds`）→ `secondaryAxisCasingLayerIds`
  （二次軸の下敷き表現、[静的レイヤー・道路表示](static-map-layers.md)参照）。
- `travelBearingDeg`/`dynamicLayerTargetTime` → 環境/評価軸の風・勾配表現が共有する入力
  （上記「動的材料の状態別表現契約」参照）。

## モバイル/デスクトップのレイアウト分岐

`useIsMobile()`（`MOBILE_BREAKPOINT_PX`=640px、`globals.css`の`@media`と一致を自動
テストで検証）で分岐する:

- デスクトップ: サイドバー（`aside.app-sidebar`）にモバイルの下部タブと同じ3区分
  「ルート設定 / ルート結果 / 地図の見え方」を同じ順序で縦積み。各区分は独立した
  `Disclosure`折りたたみで、開閉状態は`generateOpen`・`outcomeOpen`・`mapSettingsOpen`
  （localStorage）で永続化する。「ルート設定」「ルート結果」の見出し行はどちらも
  `trailing`に操作枠を持つ（前者は`renderRouteSectionHeaderActions()`の「ルート生成」
  ボタン、後者は`renderRouteResultHeaderActions()`）。「ルート結果」は候補が無い間は
  本文に案内文だけを出す。
- モバイル: 下部タブバー（ルート設定/ルート結果/地図の見え方）+`BottomSheet`（3枚が
  `mobileSheet`で排他表示、高さ`mobileSheetHeightVh`を共有）。デスクトップと同じく
  「ルート設定」シートは`RouteForm`（内部で「生成条件」「重みづけ」の2タブへさらに
  分け、`RouteSettingsPanel`を「重みづけ」タブの中身として受け取る）を描画し、
  `headerAction`propとして`renderRouteSectionHeaderActions()`（「ルート生成」ボタン）を
  デスクトップと同じヘルパーから渡す。

`BottomSheet`はposition:fixedのオーバーレイで暗幕を敷かない（表示中も地図をパン/ズーム
できる）。ドラッグ中は`onHeightChange`のみ（見た目の即時反映）、確定時に
`onHeightCommit`（永続化）を呼ぶ2段階のコールバック構成を持つ。任意の`headerAction`
propでヘッダ右側・閉じるボタンの手前へ要素を差し込める（「ルート結果」シートの
保存・GPX出力・「ルートをクリア」、下記`renderRouteOutcomeSectionBody`参照）。

## `renderRouteOutcomeSectionBody`（生成結果、デスクトップ「ルート結果」区分・
モバイル「ルート結果」タブ共通）

`routes.length === 0`の間は何も描画しない（生成前は空）。見出しは描画しない
（デスクトップは`Disclosure`の見出し、モバイルはBottomSheetの`title`が担う）。1件以上
生成された後は、Radix Tabs（`@radix-ui/react-tabs`）1段のフラットなタブ列を描画する。タブの並び順は
`routes`配列の並び順（backendが`overall_difficulty`昇順で返す、`route_generator.py`
参照）をそのまま使い、フロント側での並べ替えは行わない。タブは
**候補ごと**（`routes`の件数ぶん、「順位番号（1始まり） 距離km」だけを表示する。方位・
総合難易度はタブの中身（`RouteAxisProfile`）に出るためタブでは繰り返さない。経由地
ルート（id: `route-waypoints`）は常に1件で順位の概念が無いため、`NON_DIRECTIONAL_ROUTE_IDS`
の判定でdirection_label[固定文言]をそのまま表示する。
`RouteCandidate.is_shortest_distance`が立つ候補[目的地モードのみ]は順位番号の代わりに
「最短」と示し、他の候補には距離の後ろへ最短からの超過km[`+4.0`]を添える
[`lib/routeTabLabel.ts`]——軸設定に沿ったルートを走る対価であり、候補を見比べる
タブ列に無いと比較のたびにタブを開き直すことになるため）＋「比較」
（`ComparisonPanel`、`researchEnabled`の間だけ末尾に追加。実験スロット2件未満の
自己ガードは`ComparisonPanel`自身が持つため、非アクティブ中も状態更新を止めないよう
`forceMount`でマウントし続け、`[data-state="inactive"]`のCSSで非表示にする）で構成
される（「ルート選択」のような候補一覧をまとめる中間タブは無い）。候補数
（`RouteForm`で指定する`max_routes`件＋経由地/目的地ルート）が画面幅を超える場合は
タブ列自身が横スクロールする。`routes`・`selectedRouteId`・
`comparisonTabActive`・`generatedConditions`・`generatedRoutePreference`に加え
`experimentSlots`（比較タブ・地図重ね描き用の履歴）も同時に空にする（`handleRoutesClear`）。

`conditionsDirty`（表示中の候補を作った条件と現在のフォーム値のずれ）は、
`lib/generationRequest.ts`が組み立てる比較キーの一致で決まる。**送るpayloadと比較キーを
同じ入力（`GenerationInput`）から導出する**ため、payloadへフィールドを足したときに比較側へ
足し忘れることが起きない。比較から外すのは`IGNORED_WHEN_COMPARING`に理由付きで列挙した
ものだけで、現在は`lens_axis_id`（地図の見え方の選択で候補の選定には影響しない）。
経由地を伴う目的地ルートでは`max_routes`も外す（backendが値を無視するため）。
キーは並び順に依存しない形でJSON化する——`hard_filters`・`route_preference`は保存値からの
復元やキー整合の補完でプロパティの並びが変わりうるため。

タブ列の上には、条件変更後の未反映（`conditionsDirty`）を知らせるヒントに加え、
経由地の無い目的地ルートで指定した地点が自転車で行ける道路に繋がっていなかったため
backendが最寄りのアクセス可能な地点へ補正した場合のヒントを出す（`generatedConditions.
destinationCorrected`）。補正時は地図上の目的地ピンも
`handleGenerate`が実際に使われた地点（`conditions.corrected_destination`）へ動かす
（ピンの位置と生成されたルートの終点がずれて見えないようにする）。

「ルート結果」ヘッダの操作枠は`renderRouteResultHeaderActions()`という1つのヘルパーで、
「保存」（機能未実装のdisabled占位、`SaveIcon`）・「GPX出力」（`DownloadIcon`、
`selectedCandidate`をタップで`lib/gpxExport.ts: downloadGpx`へ渡す。候補が未選択の間は
disabled）・「ルートをクリア」（`ClearIcon`のアイコンボタン、
`handleRoutesClear`）をこの順で横並びにする操作アイコンのみを持つ。総合難易度の説明は
`RouteAxisProfile`側（総合難易度の表示の隣、`InfoPopover`）にあり、候補タブごとに
繰り返し表示される。デスクトップは「ルート結果」`Disclosure`の`trailing`、モバイルは
BottomSheetの`headerAction`propとして同じヘルパーを渡す（`routes.length > 0`の間のみ）。
候補タブ列のvalue体系はroute id・`"comparison"`・先頭固定タブ用の
`SAVED_ROUTES_TAB_VALUE`（`"saved"`、保存機能の実装までタブは描画しない。
`onValueChange`は無視する）。

外側タブの選択値は`selectedRouteId`（候補タブ選択時）と`comparisonTabActive`
（比較タブ選択時）を組み合わせて求める。`selectedRouteId`自体は比較タブを見ている間も
「最後に見ていた候補」を保持し続け、地図の色分け対象・`selectedCandidate`等の使われ方は
タブ構成に関わらず変わらない（比較タブから候補タブへ戻ると、見ていた候補がそのまま
選択された状態に戻る）。

候補タブの中身（`Tabs.Content`）は`RouteAxisProfile`単体。`RouteAxisProfile`は
総合難易度の表示・軸別内訳
（`domain/difficulty.py:
composite_difficulty`と同じ考え方で軸の重みを反映した寄与度をバー長に、生の
`axis_difficulties`値をバー色に使う。この一覧は選択操作を持たない読み取り専用）・
軸別難易度の一覧（公開軸すべて、重み0は「未使用」・値なしは「データなし」として残す）を
持つ。地図の色分け（レンズ）を選ぶ操作はここには無い（`LensControl`）。

`ComparisonPanel`へ渡す`axes`は、表示中のいずれかの実験スロットで生成時点の重み
（`ExperimentSlot.conditions.route_preference`）が>0だった軸に絞り込む（現在のライブな
`routePreference`ではない）。

## `MapView`（`Map/MapView.tsx`）との境界

`page.tsx`は`MapView`へ多数のprops（表示フラグ・色分けデータ・コールバック）を渡す。
`MapView`自身はレイヤー固有の判断ロジックを持たず、渡された値をそのままMapLibreの
source/layer操作へ変換する「汎用描画係」という位置づけを保っている
（[静的レイヤー・道路表示](static-map-layers.md)・[動的気象レイヤー](dynamic-weather-layers.md)参照）。
地図初期化用の`useEffect`は空配列依存でマウント時に1度だけ実行され、最新props値は
`redrawPropsRef`（refへ都度同期）経由で読む——`useEffect`の依存配列に載せると再マウント
のたびにMapLibreインスタンスが作り直されてしまうため。

地図キャンバスはモバイルの下部タブバー・ボトムシートの下にも描画される（`page.module.css`の
`.mobileTabBar`参照）。ルート生成直後のフィット（`fitBoundsToRoutes`）が覆われた領域へ
ルートを収めてしまわないよう、覆っているUIの高さは`page.tsx`が実測・換算して
`routeFitObscuredPx`（辺ごとのpx）で渡す——`MapView`はシート・タブバーの存在を知らない
ままでいられる。`MapView`側はそれを基本余白へ足し、対向する2辺が地図の縦・横を食い尽くす
場合だけ可視領域が残るところまで縮める（`computeRouteFitPadding`）。フィット自体は候補一覧が
変わったときだけ行うため、この値はrefから読む（シートの開閉・高さ変更では地図を動かさない）。
