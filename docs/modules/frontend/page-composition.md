# ページ全体構成・状態管理（frontend）

## 責務

`app/page.tsx`がアプリのコンポジションルート兼状態ハブ。地図（`MapView`）・ルート設定/
結果パネル（`RouteSettingsPanel`・`RouteForm`・`RouteAxisProfile`）・地図
オーバーレイ制御（`MapOverlayControls`）・研究モードの比較表
（`ComparisonPanel`）を1つのReactツリーへ束ね、状態を集約する。Next.jsのApp Router
フレームワークファイル（レイアウト・エラーバウンダリ）と、特定の機能モジュールに
属さない横断的なlib/hooks/部品もここで扱う（UI基盤の`components/ui/`・`lib/cn.ts`・
`app/globals.css`は[デザイン基盤](frontend-design-system.md)）。

**対象ファイル**

| レイヤー | ファイル |
|---|---|
| app | `page.tsx`・`layout.tsx`・`error.tsx`・`global-error.tsx` |
| hooks | `useStoredState.ts`・`useIsMobile.ts`・`useElementHeightCssVar.ts`・`useLocation.ts`・`useDebouncedValue.ts`・`useIsomorphicLayoutEffect.ts` |
| features/map/view | `useMapView.ts`（地図の見え方の状態と、地図・操作部品へ渡す値）・`mapLook.ts`（地図へ渡す見え方の値の型）・`lens.ts`（レンズから塗る軸・凡例・選択肢を導く）・`overlayChips.ts`（地図上チップの状態とレイヤー表示の保存形式）・`legendFilters.ts`（凡例で隠した行の保存先の読み書き） |
| features/map/MapView | `useLayerDataStatus.ts`（`layerDataStatus` stateの実装） |
| lib | `apiBaseUrl.ts`・`apiError.ts`・`backendInternalUrl.ts`・`fetchJson.ts`・`apiTimeouts.ts`（APIリクエストのタイムアウト。呼び出しの性質ごとの名前付き定数）・`safeStorage.ts`（localStorageの読み書きで例外を外へ出さない薄いラッパ）・`paletteCssVariables.ts`（地図に塗る色と同じ色をUIにも出す箇所へ、配信された値をCSS変数として流す。`layout.tsx`がサーバー側で`:root`へ入れる。CSSが値を持つのはライト/ダークで2値を持つものだけ） |
| features/route | `routeApi.ts`（ルート生成・プレビューAPI）・`formatDuration.ts`（秒を「1時間42分」の形にする）・`generationRequest.ts`（生成リクエストのpayloadと`conditionsDirty`の比較キーを同じ入力から導出する純関数）・`routeSplice.ts`（候補どうしが別々の道を通る区間を`edge_ids`の集合演算で求め、表示中の側と相手側を対応づけ、選んだ区間を差し替えた経路を組み立て、合成結果を生成候補と同じ並び順の規約［`overall_difficulty`昇順、基準線（所要時間が最小の候補、backendの`is_fastest`）だけは先頭固定］へ差し込む純関数。差し替えた経路の評価はbackendが行うため計算式は持たない。**並び順の規約はbackendにもある**——backendは合成結果を1件しか返さず他候補を知らないため差し込む位置をここで決めるしかなく、片方を変えたらもう片方も変える。区間を割る下限は持たず呼び出し側から受け取る［backendの較正値で、管理画面から変えられる］） |
| features/conditions | `useDepartureTime.ts`（出発時刻。選ぶまでは5分刻みの「今」へ追従し、選んだ時刻は動かさない）・`rideConditions.ts`（走行条件の出発時刻ラベルと想定速度の丸め。速度の上下限はbackendの`routeGenerateConfig`から読む） |
| types | `types/route.ts`（`RouteCandidate`等の生成APIレスポンス型） |
| components（特定モジュールの責務ではない共通部品） | `ErrorText/ErrorText.tsx`（フォームのエラー文言表示）・`BottomSheet/BottomSheet.tsx`（モバイル下部シート、下記「モバイル/デスクトップのレイアウト分岐」節参照）・`Disclosure/Disclosure.tsx`（折りたたみ表示、[ルート設定・結果パネル](route-settings-and-results.md)等が使う） |
| features/conditions/RideConditionBar | `RideConditionBar.tsx`（地図右上、走行方位アイコン直下の走行条件アイコン列本体。出発時刻・想定速度ともTravelBearingControlと同じ列の幅のアイコンボタンで、アイコンの下へ現在値（出発時刻は当日なら「12:40」、別の日は「9/24」「12:40」の2行。想定速度は「20km/h」）を出す。表示・`aria-label`・`title`は同じ文字列から作る。タップしたポップオーバー内はドラッグ式タイムライン（「今」の目盛りを選ぶと追従へ戻す）＋`input[type=datetime-local]`の直接指定[出発時刻、日本時間で読み書きする]、スライダー＋数値入力[想定速度]）・`departureTimeline.ts`（出発時刻ポップオーバーのドラッグタイムライン用の目盛り生成。気象レイヤーの実フレームには依存しない自己完結した合成タイムライン） |
| features/conditions/DynamicLayerTimeSlider | `DynamicLayerTimeSlider.tsx`（ドラッグ/横スクロールで時刻を選ぶ汎用タイムラインUI。`RideConditionBar`が出発時刻ピッカーとして使う唯一の呼び出し元） |

`apiBaseUrl.ts`/`backendInternalUrl.ts`はブラウザからのfetch先（`NEXT_PUBLIC_API_URL`）と
Next.js route handlerからのサーバー間fetch先を区別する（後者はコンテナ内部
ネットワークのURLになりうるため別変数）。`useLocation.ts`はブラウザのGeolocation APIを
扱うhookで、起点座標の取得に使う。

タイムアウトは`apiTimeouts.ts`の名前付き定数（既定15秒・状態確認5秒・カタログ10秒・
分布プレビュー60秒・管理画面の重い集計90秒）から選ぶ。**同じ呼び出しのブラウザ側
クライアントとNext.js route handler（backendへの転送）は必ず同じ定数を共有する**
——別々に持つと片方だけ延ばしてももう片方が先に打ち切って症状が変わらない。

`fetchJson.ts`/`apiError.ts`は全`services/*Api.ts`クライアントが共有するfetch骨格と
エラー正規化。骨格は「fetch→通信エラーのtry/catch→`response.ok`確認→エラーボディ解析→
`ApiError`をthrow→各段階でdebugLog記録」で、**呼び出しごとに違うのは
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
通信エラー・タイムアウトは常に`messages.failure`へ`[通信エラー]`/`[タイムアウト]`を添えた
日本語の`Error`へ包み直し、ブラウザ由来の英語の文言（`Failed to fetch`・`signal timed out`）は
`cause`とdebugLogにだけ残す——呼び出し元の多くが`error.message`をそのまま画面へ出すため、
包むかどうかを呼び出し元に選ばせると、選び忘れた経路から英語が本文へ漏れる。

## 時刻（画面全体の規約）

**画面に出す時刻は、見る人の端末の時刻帯によらず日本時間で出す**（道路データも経路も日本の中で、
backendも日本時間で扱う。`domain/time_zone.py`）。暦と時刻の取り出し・書式・日時の入力欄
（`datetime-local`は時刻帯を持たず、ブラウザは端末の時刻帯で読む）との変換は`lib/time.ts`だけが
持ち、画面は`toLocaleString`等で端末の時刻帯を使わない。

## 失敗・空・待ちの伝え方（画面全体の規約）

「取得中（待ち）」「取得できたが対象が無い（空）」「取得できなかった（失敗）」を、どの画面も
同じ規則で出し分ける。判定の実装は経路ごとに違ってよいが、**出口の規則は1つ**にする。

1. **3つを混ぜない。** 「なし」「ありません」は空にだけ使い、失敗を空の文言で出さない
   ——利用者は「その場所にはデータが無い」と読み、壊れていることに気づけない。原因を
   区別できない経路（backendが欠測と取得失敗を同じ502で返す等）は、「取得できません」の
   ように失敗側へ倒して書く。
2. **文言は常に日本語。** 失敗の文言の出所は、backendの`detail`（429の混雑案内を含む、
   HTTPエラー時）か、`messages.failure`（通信エラー・タイムアウト・本文の無いHTTPエラー）の
   どちらかだけにする（上記`fetchJson.ts`）。Next.js route handlerが自前で組み立てる`detail`
   （管理APIの転送の口`app/admin/api/[...path]`の転送失敗）も同じで、ランタイム由来の英語はサーバーのログにだけ
   残す。**エラーを受け取って言い直す側は、原因を断定
   しない**——ポーリングの連続失敗のように原因が複数ありうる場所は、最後の失敗の文言を
   添える（`features/route/routeApi.ts`）。
3. **常時見せるのは状態の合図まで、文は1タップ奥。** 地図に重なるUIは視界を削らないため、
   常時出すのは状態ドット（`components/ui/Dot`）のような小さな合図に留め、
   その意味を文で読ませる置き場は▶パネル（地図上チップ）・ポップオーバー（レンズ）に置く。
   **`title`だけに状態を持たせない**——主用途のスマホでは`title`は出ない。`title`は
   ホバーできる環境向けに同じ文言を複写する用途に限る。文を置く1タップ奥が無い1行表示
   （常設ヘッダーの`WeatherPanel`）では、状態（失敗であること）を本文の短い文言で示し、
   原因の詳細（`detail`）だけを`title`へ回す。
4. **原因の粒度は、利用者の次の行動が変わる単位まで。** 混雑（429）と通信エラーはどちらも
   「待って再試行」だが、backendの`detail`と`[通信エラー]`で区別されて届くため、`Error`を
   そのまま出す経路ではそのまま見せる。**地図タイル（MapLibreの`error`イベント）とレンズ
   （`regionApi.ts: fetchDynamicWayValues`）は原因を落とし、汎用の「取得に失敗しました。
   しばらくしてから再読み込みしてください」に揃える**。タイルの`error`イベントが運ぶ
   MapLibreの`AJAXError`はHTTPステータスを持つが本文（`detail`）は`Blob`で同期的に読めない。
   どちらの経路も原因に関わらず利用者の行動（待つ）は同じで、状態は次の取得サイクルで
   解除されるため、原因を運ぶ配線に見合う差が無い。

警報・注意報系（警報・注意報／暑さ指数／河川氾濫予報）は[API設計](../../architecture/api-design.md)の
とおりbackendがfail-openで空を返すため、フロントが拾える失敗は通信エラー・429等だけである。
拾えた失敗は**バッジが無いことを「警告なし」と読ませない**ために、常設ヘッダーへ
失敗している間だけ小さな印（`WarningBadge.tsx`の「未取得」）を出し、どの出所が取れて
いないかと失敗の文言はタップで開くポップオーバーに置く。成功している間は何も足さない
（`features/conditions/useWeatherConditions.ts: warningFetchFailures`）。backend内部の失敗は空応答と
区別できないため、この印には現れない。

## 主な構成要素（import元）

| 種別 | コンポーネント |
|---|---|
| 地図本体 | `features/map/MapView/MapView`（全静的/動的レイヤーのMapLibre実装本体） |
| 地図オーバーレイ制御 | `MapOverlayControls`（地図上チップ）・`TravelBearingControl`（走行方位ダイヤルの地図右上アイコン）・`LensControl`（地図上部中央のレンズ選択ピル）・`RideConditionBar`（走行方位アイコン直下、地図右上の走行条件アイコン列、出発時刻・想定速度） |
| ルート設定 | `RouteForm`（モード切替/距離/候補件数/生成ボタン）・`RouteSettingsPanel`（0次除外・軸選択・重み） |
| ルート結果 | `RouteAxisProfile`（候補ごとのタブの中身、軸別難易度）。候補の一覧（縦タブ）自体は独立コンポーネントを持たずpage.tsxが直接組み立てる |
| 研究モード | `ComparisonPanel`（実験スロット比較表） |
| レイアウト | `BottomSheet`（モバイル下部シート） |

## page.tsxの状態管理

状態は変更理由ごとに持ち主を分ける。**地図の見え方**（レイヤーのON/OFF・レンズ・凡例で
隠した行・表示範囲・地図から上がる取得状態）は`features/map/view/useMapView.ts`が持ち、
`page.tsx`から受け取るのはルートの文脈（候補を選んだか・区間まで確定したか）・走行条件・
生成に使われた重みだけにする——評価軸・レイヤー・外部データ源を足したときに膨らむのは
この部分だけで、軸やレイヤーの種類を知らない値だけを受け取る形にしておけば、足しても
`page.tsx`は変わらない。残り（ルートの生成と結果・区間の乗り換え・レイアウト）は`page.tsx`が
持ち、子コンポーネントへはpropsで渡す（子が独自に同じ状態を持たない）。全件の一覧は
実装を読むのが正で、ここでは**永続化するかどうかの判断基準**だけを示す——一覧を書き写すと、
状態を1つ足したときにこの節だけが古くなる。

| 永続化 | 判断基準 | 代表例 |
|---|---|---|
| `localStorage` | 利用者が自分で決めた設定で、次に開いたときも同じであってほしいもの | 評価の設定（`routePreference`・`hardFilters`）、生成条件の入力（`routeMode`・距離・候補数）、走行条件のうち想定速度、レイヤー表示（`layerVisibility`・`lens`）、パネル開閉、下部シートの高さ |
| なし | そのセッション限りの結果・場所の指定・行くたびに変わる走行条件・地図の見え方 | 生成結果（`routes`・`selectedRouteId`）、目的地・経由地のピン、出発時刻・走行方位、地図ビューポート、データ取得状態 |

地図のタップで地点を置けるのは、「ルート設定」の「条件」タブで役割を選んでいる間だけ
（`pinPlacementArmedRole`）。役割ごとの武装フラグは持たず、`PinRole`1つで表す
（[route-settings-and-results.md](route-settings-and-results.md)「地点の指定」参照）。

**場所（目的地・経由地のピン）は保存しない**——行くたびに変わるうえ、古いピンが残っていると
気づかないまま生成してしまう。保存した生成条件の入力値は、復元時にUIが受け付ける範囲内かを
検査し、外れていれば既定値のまま扱う（スライダーの範囲が縮んだ後でも範囲外の値が送られない）。

復元時の注意が要るのは、**正本がbackend側にある設定**だけである。`hardFilters`は
`features/route/hardFilterSync.ts: syncHardFilterKeys`が、保存済みの値を正本
（`routeGenerateConfig.hard_filters`）のキー集合へ整合させてから使う——キー集合の完全一致を
要求するAPIのため、フィルタが増減した後の古い保存値をそのまま送ると全リクエストが422になる。

## 動的材料（風・勾配）の状態別表現契約

`page.tsx`は風・勾配を「評価軸グループ（線、視界内の全道路へ一律色分け）」として配線する
（面塗りの表現は持たない）。両者は`[時刻, 向き]`のうち「時刻」の扱いが異なる（風のみ
時刻依存）が、「向き」は単一の共有state`travelBearingDeg`を風・勾配の両方が使う
（走行方位という1つの概念を表す単一state）:

```
travelBearingDeg（page.tsxの単一useState、TravelBearingControlで操作）。出発時刻は`features/conditions/useDepartureTime.ts`の`at`、想定速度は`assumedSpeedKmh`（いずれも地図右上の条件アイコン列`features/conditions/RideConditionBar/RideConditionBar.tsx`で操作し、生成リクエストの`start_time`/`assumed_speed_kmh`とレンズの`speed_kmh`へ同じ値が乗る）
  │
  ├─→ 風:   [時刻]出発時刻（useDepartureTime由来）
  │           │
  │           ├─→ 環境: 矢印のみ（showWindVector = layerVisibility.windVector）。走行方位に
  │           │     依存する面塗りは持たない（[地図: 動的気象レイヤー](dynamic-weather-layers.md)参照）
  │           └─→ 評価軸（線）: レンズがその軸を指している間だけ（下記の共通経路）
  │
  └─→ 勾配: （時刻非依存）
              └─→ 評価軸（線）: レンズがその軸を指している間だけ（下記の共通経路）

  評価軸（線）の共通経路（軸ごとの分岐を持たない）:
    塗っている軸 paintedAxisId = lens（ルート確定後は周囲も塗る設定の間だけ。それ以外はnull）
    useDedicatedWayValues([塗っている専用way値配信軸], 表示範囲, 走行方位, 出発時刻, 想定速度)
      （useMapViewの中。時刻・想定速度は軸カタログのneedsTime/needsSpeedが立つ軸のリクエストにだけ載る）
    軸のレイヤーを出すか = 軸id === paintedAxisId（地図側のsceneが導く）
```

**ルート確定後（`hasDetail`）**、評価軸グループの一律色分けは
**「ルート後も周囲を塗る」（既定ON）次第**で、ONの間はルート線の色分けと併せて
周囲の道路も薄く塗り続ける（`features/map/view/lens.ts: paintedAxisId`）。ルート線側の色分けは`routeStyleModes.ts`由来のモード
選択が担う。

走行方位の設定UIは`TravelBearingControl`（地図右上、MapLibreのズーム+/−・回転コントロールの
直下に置くアイコンボタン）1箇所へ集約されており、出発時刻・想定速度と同じ「走行条件」の
一部として**常時表示する**（表示条件を持たない）。中身は`RouteSettingsPanel`と同じ
`WindBearingSlider`ダイヤルをRadix Popoverで開く。

地図右上は、MapLibreのズーム+/−・回転（`MapView.tsx`の`NavigationControl`）の下へ
`TravelBearingControl`・`RideConditionBar`を積んだ**1本の列**で、幅・間隔・アイコンの大きさは
`globals.css`の`--map-ctrl-*`だけが持つ。MapLibre側のボタンの幅もそこで列の幅へ広げ、
アプリのボタンを積み始める位置はNavigationControlの既定のボタン数（3つ）から導く——
どこか1か所だけ別の値を持つと、その継ぎ目だけ間隔や幅がずれる。値を出すボタンは高さだけが
中身に合わせて伸びる。右下の現在地ボタン（44px）も、この列と中心がそろう位置に置く。

**暗黙の前提**: way_id単位の実データ本体と取得中かは、軸id→取得結果の1つの`Map`として
見え方の値（`MapLook.dedicatedWayValues`）に載る（design-principles.md構造仕様3「軸ごとに
propを新設しない」）。表示宣言（種類・単位・しきい値・段階ラベル）は軸そのもの（軸カタログの
`dedicatedAxes`の各要素の`display`）が持ち、別の値では渡さない——軸と表示宣言を別々に配ると、
片方にだけ在る軸が生まれ、それを既定値で埋める経路が要る。地図は軸カタログを共有ストアから
自分で読むため、`dedicated_way_value_layer`軸が増えてもどの受け口も変わらない。

## 状態の永続化（`hooks/useStoredState.ts`）

`useStoredState(key, defaultValue, {serialize, deserialize, autoSave, reloadKey})`が
localStorageへの保存・復元を1箇所に集約する。

- 復元は`useState`の初期化子ではなく、マウント後の`layout effect`
  （`useIsomorphicLayoutEffect`）で行う（SSR時のHTMLとハイドレーション結果のずれ防止）。
- 保存は「setter呼び出しのたびに即書き込む」方式（`autoSave`省略時true）。
- `reloadKey`: 復元処理を再実行させたい追加の依存値。`deserialize`はrefへ退避しない
  （`reloadKey`が変わった際、その時点の最新の`deserialize`クロージャで再復元する）。例:
  レンズの選択（`lens`）は`deserialize`が実行時カタログの`routeStyleModes`を参照するため、
  `axisCatalog.loaded`を`reloadKey`にする——カタログ取得前の1回だけで判定すると、軸を指す
  保存値が未知のidとして捨てられ、再訪のたびに総合難易度へ戻る。
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
  キー整合補正 → ルート生成リクエスト。整合補正は役割の違う経路へ分かれる: `RouteSettingsPanel`の
  マウント時（`useEffect`）は**stateを書き換える**、生成リクエストの組み立て
  （`features/route/routePreferenceSync.ts: routePreferenceToSend`）は**送る値だけを整える**（stateは
  触らない。パネルを開かずに生成する経路の穴埋め）。**利用者が重みを上書きしていない間
  （`weightOverrideEnabled`がfalse）と、軸カタログを取得できていない間は`route_preference`
  自体を送らず、backendの既定の重みへ委ねる**——上書きしていない利用者の保存値は利用者が
  決めた重みではなく、取得前は軸が0件のため、そのまま整合させると保存済みの重みを全部消す。
- 走行条件（走行方位・出発時刻・想定速度）→ 地図の見え方（`useMapView`の入力）・生成リクエスト・
  道の詳細（`MapView`の`rideConditions`）が同じ値を読む（上記「動的材料の状態別表現契約」参照）。
- 生成に使われた重み（生成条件`generatedConditions`の1項目、backendが生成時に使った値を返す）→ レンズの
  選択肢の「未使用」。**使う軸は生成した時点で決まる**ため、生成前は「未使用」を付けない。
- 地図の見え方の値（`useMapView`の`look`）→ `MapView`。レイヤーのON/OFF・レンズ・塗っている軸・
  隠した行・取得結果の状態そのものだけを渡し、そこから導けるもの（どのレイヤーを出すか・家族ごとの
  隠した行・二次軸の下敷き）は地図側のscene（`features/map/scene/applyToMap.ts`）が導く。
  軸カタログ・タイル世代は`MapView`と`useMapView`がそれぞれ共有ストアから読み、`page.tsx`は
  渡さない。

## モバイル/デスクトップのレイアウト分岐

`useIsMobile()`で分岐する。幅のしきい値はCSSだけが持ち（`globals.css`の`@media`が立てる
`--is-mobile`）、JSはその旗を読むだけで数値を写さない:

- デスクトップ: サイドバー（`aside.app-sidebar`）にモバイルの下部タブと同じ2区分
  「ルート設定 / ルート結果」を同じ順序で縦積み。各区分は独立した`Disclosure`折りたたみで、
  開閉状態は`generateOpen`・`outcomeOpen`（localStorage）で永続化する。「ルート設定」「ルート結果」の見出し行はどちらも
  `trailing`に操作枠を持つ（前者は`renderRouteSectionHeaderActions()`の「ルート生成」
  ボタン、後者は`renderRouteResultHeaderActions()`）。「ルート結果」の候補一覧は**左の縦タブ**
  （`Tabs.Root orientation="vertical"`）で、右に選択中候補の中身が並ぶ2カラム——横並びの
  タブは候補が増えると列が表示幅を超えて伸び、溢れた候補が存在ごと見えなくなる。
  行は「順位・距離・総合難易度（数値と長さ）」を持ち、**バーの高さには距離の倍率**
  （`features/route/difficultyLoadBar.ts`、基準は一覧の中で最も短い候補）を与える——長さが総合難易度の
  ため、塗られた面積がそのまま負荷（`difficulty_load`）になり、候補の中身の内訳バーと同じ
  見方で読める。行は**一覧の中で所要時間が最小の候補に
  「最速」、他の候補にはそこから何分余計にかかるか（`+8分`）を添える**——並び順は総合難易度の
  昇順なので「最も易しい」は先頭だが、それを走る対価（時間）は別の軸で、行を開かずに
  見比べられる必要がある。基準線は一覧の中だけで決める（backendの`is_fastest`は目的地
  モードでしか付かず、主用途の周回モードでは一度も決まらない）。時間の最上級と距離の最上級を
  同じ列へ並べると何と比べているのか読めなくなるため、**距離の「最短」は出さない**。2カラムは高さを
  揃え、狭幅では下部シートの高さいっぱいまで伸ばして余りを一覧が使う（はみ出す候補は
  一覧の中を縦スクロール）——一覧に固定の高さ上限を置くと、シートに余白があっても
  伸びずに触れない余白が残る。
  「ルート結果」は候補が無い間、
  `renderRouteOutcomeEmptyState()`が生成前・生成中・失敗（検証エラー・APIエラー・候補0件）を
  出し分ける。**生成に関するフィードバックの置き場はここ1箇所**——「ルート生成」は見出し行の
  ボタンで本文を畳んだままでも押せるため、押した結果を「ルート設定」本文へ出すと操作している
  場所から見えない。失敗時は`outcomeOpen`を開き、モバイル向けに`hasUnseenResults`も立てる
  （シートは排他表示のため勝手に開かず、タブのドットで知らせる）。
  **ルートの編集は「ルート結果」の中のモード**（`splice`。編集の元の候補・適用した乗り換え・
  評価結果の控え・処理状態を1つに持ち、抜けると中身ごと消える）で、独立した置き場を
  持たない——別の置き場にすると、どのルートを編集しているのかを編集側で選び直す形になる。
  入口は「ルート結果」ヘッダの操作アイコン列（`renderRouteResultHeaderActions`）で、
  乗り換えできない生成（周回・候補1件）と編集中には出さない——押しても何もできない入口を
  残さない。編集の元は押した候補に固定し、作ったら同じ場所が一覧へ戻る
  （[route-settings-and-results.md](route-settings-and-results.md)参照）。
- モバイル: 下部タブバー（ルート設定/ルート結果）+`BottomSheet`（2枚が`mobileSheet`で
  排他表示、高さ`mobileSheetHeightVh`を共有）。デスクトップと同じく
  「ルート設定」シートは`RouteForm`（タブの中身を描く。タブ列と選択状態は`page.tsx`側の
  `Tabs.Root`が持つ）を描画し、`headerLead`propへタブ列（`renderSettingsTabs()`）、
  `headerAction`propへ`renderRouteSectionHeaderActions()`（「ルート生成」ボタンと、
  条件が変わっている印）をデスクトップと同じヘルパーから渡す。

`BottomSheet`はposition:fixedのオーバーレイで暗幕を敷かない（表示中も地図をパン/ズーム
できる）。地図の操作ボタンは画面の下端からの距離で置いているため、シートが占める高さを
`--mobile-sheet-height`として`.mapPane`へ渡し、下端からの距離は「元の位置」と「シートの
上端のすぐ上」の大きい方にする（シートを持ち上げたときに裏へ隠れない。閉じている間は0で
従来どおり）。見出し行には差し込み口が2つあり、見出しのすぐ右（左寄せ）が`headerLead`、右上の
アクション群が`headerAction`——中身を切り替えるタブと、押して何かを走らせるボタンを
同じ行に置きつつ役割で離すため。ドラッグ中は`onHeightChange`のみ（見た目の即時反映）、確定時に
`onHeightCommit`（永続化）を呼ぶ2段階のコールバック構成を持つ。

高さは「中身に合わせる」と「利用者が決めた値を使う」の2通りで、**決めた値が常に優先される**。
保存値があること自体が「決めた」の証跡になる——自動調整は`onHeightChange`までで保存しない
ため、保存値はドラッグ/キー操作の確定でしか生まれない。`page.tsx`はマウント時に保存値の
有無を見て`autoFitHeight`を渡す。自動調整する側でも開いている間は合わせ直さない
（候補の切り替えのたびに地図の見える範囲が動かないように）が、`fitKey`が変わったときだけは
中身が別物になったとみなして合わせ直す（「ルート設定」シートはタブを渡す——切替先の中身が
開いた時点の高さに収まらないままになるため）。

**開いた時点で中身なりの高さへ合わせる**（`naturalHeightOf`）。シートが中身より高いと、
そのぶん地図が隠れたまま空白を見せることになる。開いている間は合わせ直さない——候補の
切り替え・区間クリックのたびに地図の見える範囲が動くと落ち着かないため。中身なりの高さは
**高さ指定を一時的に外して実測する**: `scrollHeight`は中身が箱より低いと箱の高さを返し、
子要素の合算も中身側のflexが引き伸ばされていると箱の高さに一致するため、どちらも縮める
判断に使えない。合わせた高さはドラッグで上書きでき、その値は次に開くまで有効
（`onHeightCommit`の保存は、実寸が取れない実行のフォールバックとして残る）。任意の`headerAction`
propでヘッダ右側・閉じるボタンの手前へ要素を差し込める（「ルート結果」シートの
GPX出力・「ルートをクリア」、下記`renderRouteOutcomeSectionBody`参照）。

## `renderRouteOutcomeSectionBody`（生成結果、デスクトップ「ルート結果」区分・
モバイル「ルート結果」タブ共通）

`routes.length === 0`の間は何も描画しない（生成前は空）。見出しは描画しない
（デスクトップは`Disclosure`の見出し、モバイルはBottomSheetの`title`が担う）。1件以上
生成された後は、Radix Tabs（`@radix-ui/react-tabs`）1段のフラットなタブ列を描画する。タブの並び順は
`routes`配列の順序をそのまま使い、**フロント側では並べ替えない**（並び順は配る側が決める）。タブは
**候補ごと**（`routes`の件数ぶん、「順位番号（1始まり） 距離km」に加えて総合難易度を
数値と長さの両方で表示する——タブを開かずに候補どうしを見比べられるようにするため。経由地
ルート（id: `route-waypoints`）は常に1件で順位の概念が無いため、`NON_DIRECTIONAL_ROUTE_IDS`
の判定でdirection_label[固定文言]をそのまま表示する。
基準線（一覧の中で所要時間が最小の候補。`fastestRouteId`）には順位番号に加えて
「最速」を添え、他の候補には距離の後ろへ基準線からの超過時間[`+12分`]を添える
[`features/route/routeTabLabel.ts`]——軸設定に沿ったルートを走る対価であり、候補を見比べる
タブ列に無いと比較のたびにタブを開き直すことになるため。**backendの`is_fastest`は
この表示に使わない**——目的地モードでしか付かず、主用途の周回では基準線が一度も
決まらない）＋「比較」
（`ComparisonPanel`、`researchEnabled`の間だけ末尾に追加。実験スロット2件未満の
自己ガードは`ComparisonPanel`自身が持つため、非アクティブ中も状態更新を止めないよう
`forceMount`でマウントし続け、`[data-state="inactive"]`のCSSで非表示にする）で構成
される（「ルート選択」のような候補一覧をまとめる中間タブは無い）。候補数
（`RouteForm`で指定する`max_routes`件＋経由地/目的地ルート）が画面幅を超える場合は
タブ列自身が横スクロールする。`routes`・`selectedRouteId`・
`comparisonTabActive`・`generatedConditions`に加え
`experimentSlots`（比較タブ・地図重ね描き用の履歴）も同時に空にする（`handleRoutesClear`）。

`conditionsDirty`（表示中の候補を作った条件と現在のフォーム値のずれ）は、
`features/route/generationRequest.ts`が組み立てる比較キーの一致で決まる。**送るpayloadと比較キーを
同じ入力（`GenerationInput`）から導出する**ため、payloadへフィールドを足したときに比較側へ
足し忘れることが起きない。比較から外すのは`IGNORED_WHEN_COMPARING`に理由付きで列挙した
ものだけで、現在は`lens_axis_id`（地図の見え方の選択で候補の選定には影響しない）。
候補数は実際に使う値を送って比べる（`useRouteFormSubmit.ts: fixedRouteCount`——経由地を伴う目的地ルートは
backendの決まった数）ので、その条件で候補数の入力を変えても印は点かない。利用者が
出発時刻を選んでいない間は`start_time`も外す——共有時刻は「今」へ5分刻みで追従するので、
放置するだけで値が変わる（何もしていないのに印が点くと、印が合図として機能しなくなる）。
キーは並び順に依存しない形でJSON化する——`hard_filters`・`route_preference`は保存値からの
復元やキー整合の補完でプロパティの並びが変わりうるため。

タブ列の上には、条件変更後の未反映（`conditionsDirty`）を知らせるヒントに加え、
経由地の無い目的地ルートで指定した地点が自転車で行ける道路に繋がっていなかったため
backendが最寄りのアクセス可能な地点へ補正した場合のヒントを出す（`generatedConditions.
destinationCorrected`）。補正時は地図上の目的地ピンも
`handleGenerate`が実際に使われた地点（`conditions.corrected_destination`）へ動かす
（ピンの位置と生成されたルートの終点がずれて見えないようにする）。

「ルート結果」ヘッダの操作枠は`renderRouteResultHeaderActions()`という1つのヘルパーで、
**選択中の候補に対する操作**を横並びにする（区間の乗り換えの入口・「GPX出力」・
「ルートをクリア」）。「GPX出力」（`DownloadIcon`、`selectedCandidate`をタップで
`features/route/gpxExport.ts: downloadGpx`へ渡す）は候補が未選択の間はdisabled。「ルートをクリア」
（`ClearRoutesIcon`＝ゴミ箱のアイコンボタン、`handleRoutesClear`）に**バツ印は使わない**
——シートの閉じる✕の隣に並ぶため、同じ形だとどちらがどちらか分からない。総合難易度の説明は
`RouteAxisProfile`側（総合難易度の表示の隣、`InfoPopover`）にあり、候補タブごとに
繰り返し表示される。デスクトップは「ルート結果」`Disclosure`の`trailing`、モバイルは
BottomSheetの`headerAction`propとして同じヘルパーを渡す（`routes.length > 0`の間のみ）。
候補タブ列のvalue体系はroute idと`"comparison"`。

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
軸ごとの詳細（軸別難易度・生値・材料内訳・説明）を開く凡例チップを持つ。1軸1行の一覧は
持たず、チップはルート設定パネルの「重み配分」と同じ形。**評価に使っていない軸（重み0）は
チップごと出さない**——内訳は候補ごとに縦へ伸びるため、使っていない軸まで並べると狭い幅で
「このルートで何が効いたか」が読めなくなる（design-principles.md「消さずに薄くする」の例外）。
重みはあるが寄与が0・欠損の軸はチップとして残る（効くはずの軸が効かなかったことも
判断材料のため）。地図の色分け（レンズ）を選ぶ操作はここには無い（`LensControl`）。

`ComparisonPanel`へ渡す`axes`は、表示中のいずれかの実験スロットで生成時点の重み
（`ExperimentSlot.conditions.route_preference`）が>0だった軸に絞り込む（現在のライブな
`routePreference`ではない）。

## `MapView`（`features/map/MapView/MapView.tsx`）との境界

`page.tsx`は`MapView`へ、見え方の値1つ（`look`）・走行条件と、ルート・地点・レイアウト由来の
値（候補・選択・経由地・覆われた高さ等）を渡す。`MapView`自身はレイヤー固有の判断ロジックを
持たず、受け取った状態をsceneへ通してMapLibreへ当てる「汎用描画係」という位置づけを保っている
（[静的レイヤー・道路表示](static-map-layers.md)・[動的気象レイヤー](dynamic-weather-layers.md)参照）。
地図初期化用の`useEffect`は空配列依存でマウント時に1度だけ実行され、そこで登録した
ハンドラは最新の値を1つのref（`latest`。いまのprops・宣言・表示ON/OFFを描画のたびに
書き写す）経由で読む——`useEffect`の依存配列に載せると再マウントのたびにMapLibre
インスタンスが作り直されてしまうため。

地図キャンバスはモバイルの下部タブバー・ボトムシートの下にも描画される。ルート生成直後のフィット（`fitBoundsToRoutes`）が覆われた領域へ
ルートを収めてしまわないよう、覆っているUIの高さ（辺ごとのpx）を測る関数を`page.tsx`が
`measureRouteFitObscuredPx`として渡し、`MapView`はフィットする瞬間にだけ呼ぶ——`MapView`は
シート・タブバーの存在を知らないままでいられ、画面の寸法を状態として持ち続けなくてよい。`MapView`側はそれを基本余白へ足し、対向する2辺が地図の縦・横を食い尽くす
場合だけ可視領域が残るところまで縮める（`computeRouteFitPadding`）。フィット自体は候補一覧が
変わったときだけ行う（シートの開閉・高さ変更では地図を動かさない）。
