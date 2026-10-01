# ページ全体構成・状態管理（frontend）

## 責務

`app/page.tsx`がアプリのコンポジションルート。地図（`MapView`）・ルート設定/
結果パネル（`RouteSettingsPanel`・`RouteForm`・`RouteAxisProfile`）・地図
オーバーレイ制御（`MapOverlayControls`）・研究モードの比較表
（`ComparisonPanel`）を1つのReactツリーへ束ねる。**`page.tsx`が持つのは画面の枠（どの区分・シートを開いているか）と、
機能の間の値の受け渡しだけ**で、機能の状態の遷移・入力の組み立て・描く中身の判断はその機能のフック・部品が持つ
（[ディレクトリ構成](../../architecture/directory-layout.md)の`app/`の約束）——機能は互いを読まないため、ある機能の状態を
別の機能へ渡す（ルートの候補を地図へ等）のはページの仕事として残る。Next.jsのApp Router
フレームワークファイル（レイアウト・エラーバウンダリ）と、特定の機能モジュールに
属さない横断的なlib/hooks/部品もここで扱う（UI基盤の`components/ui/`・`lib/cn.ts`・
`app/globals.css`は[デザイン基盤](frontend-design-system.md)）。

**対象ファイル**

| レイヤー | ファイル |
|---|---|
| app | `page.tsx`・`layout.tsx`・`error.tsx`・`global-error.tsx` |
| hooks | `useStoredState.ts`・`useIsMobile.ts`・`useElementHeightCssVar.ts`・`useLocation.ts`・`useDebouncedValue.ts`・`useIsomorphicLayoutEffect.ts` |
| features/map/view | `useMapView.ts`（地図の見え方の状態と、地図・操作部品へ渡す値）・`mapLook.ts`（地図へ渡す見え方の値の型）・`lens.ts`（レンズから塗る軸・凡例・選択肢を導く）・`overlayChips.ts`（地図上チップの状態とレイヤー表示の保存形式）・`legendFilters.ts`（凡例で隠した行の保存先の読み書き） |
| features/map/MapView | `useLayerDataStatus.ts`（MapLibreのソースイベントからレイヤーごとの取得状態を算出して渡す） |
| lib | `apiBaseUrl.ts`・`apiClient.ts`（backendのAPIを呼ぶ口と、全呼び出しが共有する骨格。下記）・`apiPath.ts`（アプリ自身が呼ばないURL［地図ライブラリへ渡すタイル・スタイル］のパスをOpenAPIの宣言と型で照合して作る）・`apiError.ts`・`backendInternalUrl.ts`・`queryClient.ts`（画面のデータ取得が共有するTanStack Queryのキャッシュ。下記「データ取得の骨格」）・`apiTimeouts.ts`（APIリクエストのタイムアウト。呼び出しの性質ごとの名前付き定数）・`safeStorage.ts`（localStorageの読み書きで例外を外へ出さない薄いラッパ）・`paletteCssVariables.ts`（地図に塗る色と同じ色をUIにも出す箇所へ、配信された値をCSS変数として流す。`layout.tsx`がサーバー側で`:root`へ入れる。CSSが値を持つのはライト/ダークで2値を持つものだけ）・`mapOverlayEdges.ts`（地図の上に重ねる部品へ付ける「どの辺を覆うか」の印と、印の付いた部品が覆う幅の実測。印を付ける部品は地図の機能の外にもあるので共有の層に置く。下記「`MapView`との境界」） |
| features/route | `routeApi.ts`（ルート生成・プレビューAPI）・`formatDuration.ts`（秒を「1時間42分」の形にする）・`generationRequest.ts`（生成リクエストのpayloadと`conditionsDirty`の比較キーを同じ入力から導出する純関数）・`routeSplice.ts`（候補どうしが別々の道を通る区間を`edge_ids`の集合演算で求め、表示中の側と相手側を対応づけ、選んだ区間を差し替えた経路を組み立て純関数。差し替えた経路の評価はbackendが行うため計算式は持たない。合成結果も生成候補と同じ並び（所要時間の短い順、`routeTabLabel.ts: orderByDuration`）へ入れる。区間を割る下限は持たず呼び出し側から受け取る［backendの較正値で、管理画面から変えられる］） |
| features/conditions | `useRideConditions.ts`（走行条件: 走行方位・出発時刻・想定速度。想定速度だけを保存し、保存値は画面の範囲内の整数だけを受け入れる）・`useDepartureTime.ts`（出発時刻。選ぶまでは5分刻みの「今」へ追従し、選んだ時刻は動かさない）・`rideConditions.ts`（走行条件の出発時刻ラベルと想定速度の丸め。速度の上下限はbackendの`routeGenerateConfig`から読む） |
| types | `types/route.ts`（`RouteCandidate`等の生成APIレスポンス型） |
| components（特定モジュールの責務ではない共通部品） | `ErrorText/ErrorText.tsx`（フォームのエラー文言表示）・`BottomSheet/BottomSheet.tsx`（モバイル下部シート、下記「モバイル/デスクトップのレイアウト分岐」節参照）・`Disclosure/Disclosure.tsx`（折りたたみ表示、[ルート設定・結果パネル](route-settings-and-results.md)等が使う） |
| features/conditions/RideConditionBar | `RideConditionBar.tsx`（地図右上、走行方位アイコン直下の走行条件アイコン列本体。出発時刻・想定速度ともTravelBearingControlと同じ列の幅のアイコンボタンで、アイコンの下へ現在値（出発時刻は当日なら「12:40」、別の日は「9/24」「12:40」の2行。想定速度は「20km/h」）を出す。表示・`aria-label`・`title`は同じ文字列から作る。タップしたポップオーバー内はドラッグ式タイムライン（「今」の目盛りを選ぶと追従へ戻す）＋`input[type=datetime-local]`の直接指定[出発時刻、日本時間で読み書きする]、スライダー＋数値入力[想定速度]）・`departureTimeline.ts`（出発時刻ポップオーバーのドラッグタイムライン用の目盛り生成。気象レイヤーの実フレームには依存しない自己完結した合成タイムライン） |
| features/conditions/TravelBearingControl | `TravelBearingControl.tsx`（地図右上の走行方位のアイコンボタン。押すと`WindBearingSlider`のダイヤルをPopoverで開く。詳しくは[ルート設定・結果パネル](route-settings-and-results.md)） |
| features/conditions/DynamicLayerTimeSlider | `DynamicLayerTimeSlider.tsx`（ドラッグ/横スクロールで時刻を選ぶ汎用タイムラインUI。`RideConditionBar`が出発時刻ピッカーとして使う唯一の呼び出し元） |

`apiBaseUrl.ts`/`backendInternalUrl.ts`はブラウザからのfetch先（`NEXT_PUBLIC_API_URL`）と
Next.js route handlerからのサーバー間fetch先を区別する（後者はコンテナ内部
ネットワークのURLになりうるため別変数）。

**backendのAPIは`apiClient.ts`の呼び出し口（openapi-fetch）で呼び、パス・問い合わせの項目・本文・応答の型は
OpenAPIの生成物（`types/generated/api.d.ts: paths`）から推論させる。** 呼ぶ側はパスも応答の型も手で書かない——手で書いた
型はbackendの応答の形が変わっても追従せず、画面から実際に呼ぶまで食い違いに気づけない。宣言に無いパス・問い合わせの項目の
名前・必須の項目の欠けも型検査で落ちる（FastAPIは宣言に無い問い合わせの項目を既定では黙って無視するので、手で書いた名前が
古くなると、任意の項目は届かないまま応答が返る）。値がnull・undefinedの項目は付けない（空文字は付く。付けたくない呼ぶ側が
undefinedにする）。パスの`{名前}`へ入る値は呼び出し口が1区切りとして符号化する。

| 呼び出し口 | 叩く先 |
|---|---|
| `backendApi` | backend（`API_BASE_URL`）の契約にある口 |
| `adminApiClient` | 管理API。backendの`/api/admin<X>`を同一オリジンの口`/admin/api<X>`（`app/admin/api/[...path]/route.ts`）経由で呼ぶ。パスは`/api/admin`より後を書く（例: backend `GET /api/admin/db-status`は`adminApiClient.GET("/db-status")`）。型は`paths`から`/api/admin`で始まるものだけを抜いて接頭辞を外したもので、backendのパスが変われば型検査で落ちる——接頭辞を実行時に書き換えないので、要求を作り直す手間が無い |
| `fetchJson(url)` | 応答の形がbackendの契約に無い口（気象庁の配信をそのまま返す転送`/api/jma-tile/{path}`・フロント自身のroute handler`/api/version`）。応答の型は呼ぶ側の約束で、検査されない |

**応答の型は生成型をそのまま使い、画面で補正しない。** 既定値付きの項目も契約で必須になり、GeoJSONの線も契約が形を
持つ（[横断的な基盤](../backend/cross-cutting-infrastructure.md)「Pydanticモデルの基底」）。状態で形の変わる応答（生成の
ジョブの状態・気象庁タイルの在否インデックス）は共用体のモデルが無いため、`types/route.ts`が口の応答の型を`paths`から引く。

**アプリ自身が呼ばないURL（地図ライブラリへ渡すタイル・スタイル・気象庁の配信のテンプレート）のパスは`apiPath`
（`lib/apiPath.ts`）で作る。** 引数は`paths`のキーで、`{名前}`の値を渡すと埋める（渡さなかった名前は残る——タイルの
`{z}/{x}/{y}`は地図ライブラリが埋める。区切りの`/`を含む値もそのまま埋める）。ベースURL（`tileBaseUrl()`）は呼び出し側が付ける。

`useLocation.ts`はブラウザのGeolocation APIを扱うhookで、起点座標の取得に使う。

タイムアウトは`apiTimeouts.ts`の名前付き定数（既定15秒・状態確認5秒・カタログ10秒・
分布プレビュー60秒・管理画面の重い集計90秒）から選ぶ。**同じ呼び出しのブラウザ側
クライアントとNext.js route handler（backendへの転送）は必ず同じ定数を共有する**
——別々に持つと片方だけ延ばしてももう片方が先に打ち切って症状が変わらない。

`apiClient.ts`/`apiError.ts`は全呼び出しが共有する骨格とエラー正規化。骨格（`requestApi`）は呼び出し口の1回の呼び出しを包み、
「開始→通信の失敗・HTTPの失敗・本文の解析の失敗・成功のどれかをdebugLogに記録→失敗は`Error`をthrow」を行う。
**呼び出しごとに違うのは、待ち時間・ログのカテゴリ・エラー文言・成功ログへ足す項目だけ**で、それを引数で受け取る。
取得（GET）の多くは文言を`errorLabel`から「◯◯の取得/解析に失敗しました」で組み立てる（`getOptions`）。通信の失敗は
openapi-fetchのmiddlewareの`onError`で包み直し、本文の解析の失敗は応答が届いた後の例外として見分ける（`onResponse`で
届いたことを記録する）。HTTPの失敗は呼び出し口が例外にせず`error`として返すので、骨格が`detail`から文言を作って投げる。
呼び出し口は作った時点の`fetch`を握るので、呼ぶたびに`globalThis.fetch`を引く関数を渡している（テストが差し替えた`fetch`を届けるため）。

`x-request-id`とHTTPステータスは失敗のdebugLogに残し、投げる`Error`の`message`には入れない。
リクエストIDは開発者向け（debugLog・`BackendLogsPanel`）の情報で、画面へ出す文言に混ぜると
利用者に意味が無いまま長くなり、狭い幅のレイアウト（常設ヘッダー）を溢れさせる。

**暗黙の前提**: 骨格を各クライアントへ写経すると、片方だけ改良された非対称が静かに生まれる
（タイムアウト判別と`error.cause`のログがPOST系1箇所にしか無い状態が実際に生まれていた）。
通信エラー・タイムアウトは常に`messages.failure`へ`[通信エラー]`/`[タイムアウト]`を添えた
日本語の`Error`へ包み直し、ブラウザ由来の英語の文言（`Failed to fetch`・`signal timed out`）は
`cause`とdebugLogにだけ残す——呼び出し元の多くが`error.message`をそのまま画面へ出すため、
包むかどうかを呼び出し元に選ばせると、選び忘れた経路から英語が本文へ漏れる。

## データ取得の骨格（TanStack Query）

画面がbackendから値を取り、部品の間で共有し、取り直す骨格（同じ取得の重複排除・最新の応答の採用・
読み込み中と失敗の状態・一度届いた値を失敗で巻き戻さない）はTanStack Queryが持つ。フックは`useQuery`へ
キーと取得の関数を渡し、その取得に固有の約束（いつ取り直すか・読み手が消えた後も残すか）だけを設定に書く。
新しく書くフックは、自前の取り消しの印・連番・進行中の取得の共有を持たない。

- **Providerを置かず、クライアントを引数で渡す**（`useQuery(options, getQueryClient())`）。Providerを置くと、
  取得するフックを含む部品を描くテストがすべて包みを要する。サーバーでの描画は利用者をまたいで値を共有
  しないよう、呼ぶたびに新しいクライアントを作る（サーバーでは取得を走らせないので空のまま捨てられる）。
- **既定の自動の再試行・画面へ戻ったとき・通信が戻ったときの取り直しは切る**（`queryClient.ts`）。取り直す
  契機はフックの宣言（マウント・キーの変化・`refetchInterval`）だけにする。再試行は失敗の表示を遅らせ、
  backendのレート上限へ重ねて当たる。**定期の取り直しは画面が裏にある間も続ける**——戻ったときに取り直さないので、
  裏で止めると戻ってから次の周期まで古い値（雨雲・警報）が残る。
- **読み手が消えても値はキャッシュに残り（既定の5分）、再び読むと即座に出して裏で取り直す**。表示を消している間を
  「まだ取りに行っていない」として見せたい取得（地図のチップの取得状態）は、フックが無効の間だけ未取得を返す。
- **キーをまたいで前の値を使う取得は、refを持たずキャッシュから引く**。`useQuery`の`placeholderData: keepPreviousData`は
  1つの観測者の前のキーの値を渡すが、`useQueries`は観測者をキーで対応付けるため、キーが変わった観測者に前の値を
  渡さない（`query-core/src/queriesObserver.ts: #findMatchingObservers`）。取り損ねた地点を前の格子で補う取得は、同じ
  種類のキーのうち最後に届いた値を引き（`features/map/useWeatherGrid.ts`）、件数が実行時に変わる取得で取り直しの間に
  前の値を残すものは、全体を1つのキーで取ってその中で要素ごとの答えを`fetchQuery`で引く
  （`features/map/useDedicatedWayValues.ts`）。
- テストでは、取得の結果は区切り（`setTimeout(0)`、`query-core/src/notifyManager.ts`）ごとに購読者へ届く。応答を
  返した直後に同期で確かめず、`waitFor`か区切りを待つ（偽の時計で`setTimeout`まで止めると届かない）。
- 取得の関数の中身（通信・ログ・文言）は`apiClient.ts`・`services/*Api.ts`のまま。キャッシュは呼び出し口の
  外側に被せるだけで、呼び出し口を置き換えない。

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
   どちらかだけにする（上記`apiClient.ts`）。Next.js route handlerが自前で組み立てる`detail`
   （管理APIの転送の口`app/admin/api/[...path]`の転送失敗）も同じで、ランタイム由来の英語はサーバーのログにだけ
   残す。**エラーを受け取って言い直す側は、原因を断定
   しない**——ポーリングの連続失敗のように原因が複数ありうる場所は、最後の失敗の文言を
   添える（`features/route/routeApi.ts`）。
3. **常時見せるのは状態の合図まで、文は1タップ奥。** 地図に重なるUIは視界を削らないため、
   常時出すのは状態ドット（`components/ui/Dot`）のような小さな合図に留め、
   その意味を文で読ませる置き場は▶パネル（地図上チップ）・ポップオーバー（レンズ）に置く。
   ただし待ちは文にせずドットだけで示す——パネルを開いたまま絞り込むと取り直しのたびに
   文が一瞬出ては消え、パネルの中身が揺れる。
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

警報・注意報系（警報・注意報／暑さ指数／河川氾濫予報）の空の応答は「出ていない」だけを表し、backendが
配信元から取れなかったときは通信の失敗・429と同じく失敗（502、[API設計](../../architecture/api-design.md)）で届く。
失敗は**バッジが無いことを「警告なし」と読ませない**ために、常設ヘッダーへ
失敗している間だけ小さな印（`WarningBadge.tsx`の「未取得」）を出し、どの出所が取れて
いないか・失敗の文言・取れない間に何が起きているか（`effect`）はタップで開くポップオーバーに置く。
成功している間は何も足さない（`features/conditions/useWeatherConditions.ts: warningFetchFailures`）。

同じ印には、**画面の前提になるデータの取得失敗**も並べる。例: 軸一覧（`useAxisCatalog`の`failed`、
`app/page.tsx`が警報の失敗に足す）は、取れないと地図は道路・スポット・事故を描けず、生成は重み配分を
送れず、合成は区間を割れない——どれも画面の中では「無い」ように見えるだけで、既定で開く条件タブ・
地図のどこにも理由が出ない。ポップオーバーの項目に再試行（`onRetry`）を持たせ、ここから取り直せる。
この印に並べるのは「取れていないと、画面が正常に見えたまま中身が違う」データで、取れない間の
画面の振る舞いを文（`effect`）で言えるものに限る。
現在地も同じ印に並べる: 位置が分からない間（`useLocation`の`locationSource`が仮の地点のまま）は、天候・警報を
仮の地点で取らず（どこの値かが画面に出ないまま、利用者の場所の値として読まれる）、印の「現在地」から位置を取り直せる。
地図で出発地を置けば、その地点で取る。

## 主な構成要素（import元）

| 種別 | コンポーネント |
|---|---|
| 地図本体 | `features/map/MapView/MapView`（全静的/動的レイヤーのMapLibre実装本体） |
| 地図オーバーレイ制御 | `MapOverlayControls`（地図上チップ）・`TravelBearingControl`（走行方位ダイヤルの地図右上アイコン）・`LensControl`（地図上部中央のレンズ選択ピル）・`RideConditionBar`（走行方位アイコン直下、地図右上の走行条件アイコン列、出発時刻・想定速度） |
| ルート設定 | `RouteForm`（モード切替/距離/候補件数/生成ボタン）・`RouteSettingsPanel`（0次除外・軸選択・重み） |
| ルート結果 | `features/route/RouteOutcome/RouteOutcome.tsx`（「ルート結果」の中身: 空の状態・候補の一覧［縦タブ］・候補の操作・区間の詳細・比較・編集面）・`RouteAxisProfile`（候補ごとのタブの中身、軸別難易度） |
| 研究モード | `ComparisonPanel`（実験スロット比較表） |
| レイアウト | `BottomSheet`（モバイル下部シート） |

## page.tsxの状態管理

状態は変更理由ごとに持ち主を分ける。**地図の見え方**（レイヤーのON/OFF・レンズ・凡例で
隠した行・表示範囲・地図から上がる取得状態）は`features/map/view/useMapView.ts`が持ち、
`page.tsx`から受け取るのはルートの文脈（候補を選んだか・区間まで確定したか）・走行条件・
生成に使われた重みだけにする——評価軸・レイヤー・外部データ源を足したときに膨らむのは
この部分だけで、軸やレイヤーの種類を知らない値だけを受け取る形にしておけば、足しても
`page.tsx`は変わらない。**区間の乗り換え**は`features/route/useSpliceSession.ts`が持ち、`page.tsx`は
候補の一覧と生成の入力を渡して、地図へ渡す値と編集面へ渡す値を受け取る。
**生成の条件**（「ルート設定」の入力）は`features/route/useGenerationConditions.ts`、**生成**（送信・進み方・案内・
条件のずれ・実験スロット）は`features/route/useRouteGeneration.ts`、**走行条件**は`features/conditions/useRideConditions.ts`が持つ。
**結果**（候補・選択・地図で押した区間・比較タブ・生成に使われた重み）は`features/route/useRouteResults.ts`が持ち、
生成と乗り換えは作った候補を`page.tsx`経由でそこへ入れる（地図の見え方が生成に使われた重みを読み、生成が地図のレンズを
読むため、結果を生成の側に置くと呼ぶ順が回る）。「ルート結果」の中身は`features/route/RouteOutcome/RouteOutcome.tsx`が結果・生成・乗り換えの値から描く。
残り（画面の枠: 区分・シートの開閉と高さ、「ルート設定」のタブ、新着の印）は`page.tsx`が持ち、子コンポーネントへはpropsで渡す
（子が独自に同じ状態を持たない）。**機能の間の受け渡しには、ある機能の変化が別の機能の振る舞いを変えるものがある**
（生成を消す・作り直すと乗り換えの編集が終わる〔生成の入力を渡すため〕、候補の有無が条件のずれの判定に効く、編集中は
地図で地点も区間も扱わない）。どれも各機能の単体では見えないので、`app/page.test.tsx`が受け渡しとして確かめる。全件の一覧は
実装を読むのが正で、ここでは**永続化するかどうかの判断基準**だけを示す——一覧を書き写すと、
状態を1つ足したときにこの節だけが古くなる。

| 永続化 | 判断基準 | 代表例 |
|---|---|---|
| `localStorage` | 利用者が自分で決めた設定で、次に開いたときも同じであってほしいもの | 評価の設定（`routePreference`・`hardFilters`）、生成条件の入力（`routeMode`・距離・候補数）、走行条件のうち想定速度、レイヤー表示（`layerVisibility`・`lens`）、パネル開閉、下部シートの高さ |
| なし | そのセッション限りの結果・場所の指定・行くたびに変わる走行条件・地図の見え方 | 生成結果（`routes`・`selectedRouteId`）、目的地・経由地のピン、出発時刻・走行方位、地図ビューポート、データ取得状態 |

地図のタップで地点を置けるのは、「ルート設定」の「条件」タブで役割を選んでいる間だけ
（`pinPlacementArmedRole`）。地図で地点・区間を扱えるのは、そのパネルを見ている間だけで、デスクトップでは
パネル（サイドバー）を畳んでいる間は区分が開いていても扱わない（中身が見えないまま地図で地点が動かないように）。役割ごとの武装フラグは持たず、`PinRole`1つで表す
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
時刻依存）が、「向き」は単一の共有state（走行方位）を風・勾配の両方が使う
（走行方位という1つの概念を表す単一state）:

```
走行方位（`features/conditions/useRideConditions.ts: bearingDeg`、TravelBearingControlで操作）。出発時刻は`features/conditions/useDepartureTime.ts: at`、想定速度は`useRideConditions.ts: speedKmh`（いずれも地図右上の条件アイコン列`features/conditions/RideConditionBar/RideConditionBar.tsx`で操作し、生成リクエストの`start_time`/`assumed_speed_kmh`とレンズの`speed_kmh`へ同じ値が乗る）
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

地図右上は、MapLibreのズーム+/−・回転（`MapView.tsx: NavigationControl`）の下へ
`TravelBearingControl`・`RideConditionBar`を積んだ**1本の列**で、幅・間隔・アイコンの大きさは
`globals.css`の`--map-ctrl-*`だけが持つ。MapLibre側のボタンの幅もそこで列の幅へ広げ、
アプリのボタンを積み始める位置はNavigationControlの既定のボタン数（3つ）から導く——
どこか1か所だけ別の値を持つと、その継ぎ目だけ間隔や幅がずれる。値を出すボタンは高さだけが
中身に合わせて伸びる。右下の現在地ボタン（44px）も、この列と中心がそろう位置に置く。
MapLibreが自分の部品（ズーム・方位のボタン、出典の開閉、ポップアップの閉じる、地図そのもの）に付ける読み上げ名・titleは
既定が英語のため、地図を作るときの`locale`でこの地図が使う部品の分を日本語へ上書きする（`MapView.tsx: MAP_UI_LOCALE`）。
MapLibreの部品を新しく足すときは、その部品の文言のキー（`maplibre-gl/src/ui/default_locale.ts`）も足す。

**暗黙の前提**: way_id単位の実データ本体と取得中かは、軸id→取得結果の1つの`Map`として
見え方の値（`MapLook.dedicatedWayValues`）に載る（design-principles.md構造仕様3「軸ごとに
propを新設しない」）。表示宣言（種類・単位・しきい値・段階ラベル）は軸そのもの（軸カタログの
`dedicatedAxes`の各要素の`display`）が持ち、別の値では渡さない——軸と表示宣言を別々に配ると、
片方にだけ在る軸が生まれ、それを既定値で埋める経路が要る。地図は軸カタログを共有ストアから
自分で読むため、`dedicated_way_value_layer`軸が増えてもどの受け口も変わらない。

## 状態の永続化（`hooks/useStoredState.ts`）

`useStoredState(key, defaultValue, {serialize, deserialize, reloadKey})`が
localStorageへの保存・復元を1箇所に集約する。

- 復元は`useState`の初期化子ではなく、マウント後の`layout effect`
  （`useIsomorphicLayoutEffect`）で行う（SSR時のHTMLとハイドレーション結果のずれ防止）。
- 保存は「setter呼び出しのたびに即書き込む」方式。途中の値を保存したくないもの（モバイルのシートの
  ドラッグ中の高さ）は、途中の値を別の`useState`で持ち、確定した値だけをsetterへ渡す。
- `reloadKey`: 復元処理を再実行させたい追加の依存値。`deserialize`はrefへ退避しない
  （`reloadKey`が変わった際、その時点の最新の`deserialize`クロージャで再復元する）。例:
  レンズの選択（`lens`）は`deserialize`が実行時カタログの`routeStyleModes`を参照するため、
  `axisCatalog.loaded`を`reloadKey`にする——カタログ取得前の1回だけで判定すると、軸を指す
  保存値が未知のidとして捨てられ、再訪のたびに総合難易度へ戻る。
- `useStoredJsonState`は`JSON.stringify`/`JSON.parse`を既定にした薄いラッパー、`useStoredBooleanState`は
  それに加えて保存値が真偽値かまで確かめるラッパー。
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

- 重み（保存値、`RouteSettingsPanel`が編集）→ `features/route/routePreferenceSync.ts: alignRoutePreference`で
  公開軸へキーを揃えた値 → 重みタブ・ルート生成リクエスト（`routePreferenceToSend`）・道の評価（`MapView`）・
  結果の重みの表示。**揃えるのは`useGenerationConditions.ts`が読むときの1か所だけ**で、どの読み手も同じ揃えた値を読む
  （保存値は書き換えず、利用者が次に重みを動かしたときに揃った形で書かれる）。**利用者が重みを上書きしていない間
  （`weightOverrideEnabled`がfalse）と、軸カタログを取得できていない間は`route_preference`
  自体を送らず、backendの既定の重みへ委ねる**——上書きしていない利用者の保存値は利用者が
  決めた重みではなく、取得前は軸が0件のため、そのまま整合させると保存済みの重みを全部消す。
- 走行条件（走行方位・出発時刻・想定速度）→ 地図の見え方（`useMapView`の入力）・生成リクエスト・
  道の詳細（`MapView`の`rideConditions`）が同じ値を読む（上記「動的材料の状態別表現契約」参照）。
- 生成に使われた重み（`useRouteResults.ts: usedWeights`。backendが生成時に使った値を返し、生成が結果と一緒に渡す）→ レンズの
  選択肢の「未使用」。生成前は代わりに今の設定の重み（`useMapView`の`currentWeights`）で分ける——重みタブが薄く出す軸と
  同じ軸が「未使用」に並ぶ。
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
  ため、塗られた面積がそのまま負荷（`overall_difficulty.load`）になり、候補の中身の道のりのグラフ
  （`DifficultyProfile`、面積が負荷）と同じ見方で読める。行は**一覧の中で所要時間が最小の候補に
  その所要時間と最速の印（時計のアイコン）、他の候補にはそこから何分余計にかかるか（`+8分`）を添える**——並び順は所要時間の短い順で、
  易しさ（総合難易度）は行の数値と帯で見比べる。基準線は一覧の中だけで決める（backendの応答は基準線に
  印を付けない。周回・目的地・区間を乗り換えて作った候補を同じ判定で比べる）。時間の最上級と距離の最上級を
  同じ列へ並べると何と比べているのか読めなくなるため、**距離の「最短」は出さない**。2カラムは高さを
  揃え、狭幅では下部シートの高さいっぱいまで伸ばして余りを一覧が使う（はみ出す候補は
  一覧の中を縦スクロール）——一覧に固定の高さ上限を置くと、シートに余白があっても
  伸びずに触れない余白が残る。
  「ルート結果」は候補が無い間、
  `features/route/RouteOutcome/RouteOutcome.tsx`が生成前・生成中・失敗（検証エラー・APIエラー・候補0件）を
  出し分ける。**生成に関するフィードバックの置き場はここ1箇所**——「ルート生成」は見出し行の
  ボタンで本文を畳んだままでも押せるため、押した結果を「ルート設定」本文へ出すと操作している
  場所から見えない。**候補がある間に押した「生成」が通らなかったとき（検証エラー・APIエラー）も、
  前の候補を残したまま先頭に「作り直せませんでした。」＋理由を出す**（`RouteOutcome.tsx`）——
  候補だけが並んだままだと作り直せたように見え、前の条件の候補で走り出しうる。候補を消すと
  見ていた候補も地図のルートも失い、混雑は待てば通るため残す。この文言は次に「生成」を押した時点・
  「全消去」・合成の作成で消える。候補0件は候補を空にするので、この形にはならない。
  結果が出たら`outcomeOpen`を開き、モバイル向けに`unseenOutcome`も立てる
  （シートは排他表示のため勝手に開かず、タブのドットで知らせる）。
  **ルートの編集は「ルート結果」の中のモード**（`features/route/useSpliceSession.ts`。編集の元の候補・適用した乗り換え・
  評価結果の控え・処理状態を1つに持ち、抜けると中身ごと消える）で、独立した置き場を
  持たない——別の置き場にすると、どのルートを編集しているのかを編集側で選び直す形になる。
  入口は候補のタブの中身の先頭にある「合成」（`RouteOutcome.tsx`の候補の操作）で、
  乗り換えできない生成（周回・候補1件）と編集中、区間を割る下限（軸カタログが運ぶ較正値）を
  引けない間には出さない——押しても何もできない入口・較正と違う切り方で動く入口を残さない。編集の元は押した候補に固定し、作ったら同じ場所が一覧へ戻る
  （[route-settings-and-results.md](route-settings-and-results.md)参照）。
- モバイル: 下部タブバー（ルート設定/ルート結果）+`BottomSheet`（2枚が`mobileSheet`で
  排他表示、高さ`mobileSheetHeightVh`を共有）。「ルート結果」タブの点は、まだ開いていない結果
  （`unseenOutcome`）か条件の変更（`conditionsDirty`）で点き、**失敗のときだけ赤、それ以外は橙**
  （`outcomeTabSignal`）——条件の変更と新しい結果は「開けば新しいものがある」で取る行動が同じなので
  分けず、急いで見るべき失敗だけを見分けさせる。点は色だけなので、意味をタブの`aria-description`にも持たせる。デスクトップと同じく
  「ルート設定」シートは`RouteForm`（タブの中身を描く。タブ列と選択状態は`page.tsx`側の
  `Tabs.Root`が持つ）を描画し、`headerLead`propへタブ列（`renderSettingsTabs()`）、
  `headerAction`propへ`renderRouteSectionHeaderActions()`（「ルート生成」ボタンと、
  条件が変わっている印）をデスクトップと同じヘルパーから渡す。

`BottomSheet`はposition:fixedのオーバーレイで暗幕を敷かない（表示中も地図をパン/ズーム
できる）。地図の操作ボタンは画面の下端からの距離で置いているため、シートが占める高さを
`--mobile-sheet-height`として地図ペイン（`app/page.tsx: mapPaneRef`）へ渡し、下端からの距離は「元の位置」と「シートの
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
（`onHeightCommit`の保存は、実寸が取れない実行のフォールバックとして残る）。`headerAction`
propでヘッダ右側・閉じるボタンの手前へ要素を差し込む（「ルート結果」シートの
「全消去」、下記「ルート結果の中身」参照。差し込むものが無い間は`undefined`を渡す）。

## ルート結果の中身（`features/route/RouteOutcome/RouteOutcome.tsx`。デスクトップ「ルート結果」区分・
モバイル「ルート結果」タブ共通）

候補が無い間は上の空の状態（生成前・生成中・失敗）を出す。見出しは描画しない
（デスクトップは`Disclosure`の見出し、モバイルはBottomSheetの`title`が担う）。1件以上
生成された後は、Radix Tabs（`@radix-ui/react-tabs`）1段のフラットなタブ列を描画する。タブの並び順は
**所要時間の短い順**（`routeTabLabel.ts: orderByDuration`。同着は受け取った並び＝backendの総合難易度の昇順を保つ）。
生成の結果を受け取ったときと、区間を乗り換えて作った候補を足したときに並べ直してから`routes`へ入れるので、一覧・最初に
選ぶ候補（先頭＝最も早く着く候補）・行の番号が同じ並びになる。研究モードの実験スロットの代表だけは、backendの並びの
先頭（総合難易度が最小）を使う。タブは
**候補ごと**（`routes`の件数ぶん、「順位番号（1始まり） 距離km」に加えて総合難易度を
数値と長さの両方で表示する——タブを開かずに候補どうしを見比べられるようにするため。経由地
ルート（id: `route-waypoints`）は常に1件で順位の概念が無いため、`NON_DIRECTIONAL_ROUTE_IDS`
の判定でdirection_label[固定文言]をそのまま表示する。
基準線（一覧の中で所要時間が最小の候補。`fastestRouteId`）には順位番号に加えて
その所要時間と最速の印を添え、他の候補には距離の後ろへ基準線からの超過時間[`+12分`]を添える
[`features/route/routeTabLabel.ts`]——軸設定に沿ったルートを走る対価であり、候補を見比べる
タブ列に無いと比較のたびにタブを開き直すことになるため）＋「比較」
（`ComparisonPanel`、`researchEnabled`の間だけ末尾に追加。実験スロット2件未満の
自己ガードは`ComparisonPanel`自身が持つため、非アクティブ中も状態更新を止めないよう
`forceMount`でマウントし続け、`[data-state="inactive"]`のCSSで非表示にする）で構成
される（「ルート選択」のような候補一覧をまとめる中間タブは無い）。候補数
（`RouteForm`で指定する`max_routes`件＋経由地/目的地ルート）がシートの高さを超える場合は
候補一覧の中だけが縦スクロールする（右の中身はスクロールしない）。`routes`・`selectedRouteId`・
`comparisonTabActive`・生成に使われた重みに加え、生成の側の作った条件と
`experimentSlots`（比較タブ・地図重ね描き用の履歴）も同時に空にする（`handleRoutesClear`→`useRouteGeneration.ts: clear`）。

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

タブ列の上には、条件変更後の未反映（`conditionsDirty`）を知らせるヒント（作り直しの失敗を出している間は、
それが前の条件の候補であることも伝えているので出さない）に加え、
経由地の無い目的地ルートで指定した地点が自転車で行ける道路に繋がっていなかったため
backendが最寄りのアクセス可能な地点へ補正した場合のヒントを出す（`useRouteGeneration.ts`の
`destinationCorrected`）。補正時は地図上の目的地ピンも
生成が実際に使われた地点（`conditions.corrected_destination`）へ動かす
（ピンの位置と生成されたルートの終点がずれて見えないようにする）。

「ルート結果」ヘッダの操作枠（`renderRouteResultHeaderActions()`）には**候補すべてに効く操作だけ**を置く
（「全消去」、`ClearRoutesIcon`、`handleRoutesClear`）。候補1本に効く操作（「合成」＝区間の乗り換えの入口・
「GPX」＝`features/route/gpxExport.ts: downloadGpx`）は`RouteOutcome.tsx`がその候補のタブの中身の
先頭に置く——見出しに並べると、どれが選んでいる1本だけに効くのか見分けられない。「全消去」に**バツ印は使わない**
——シートの閉じる✕の隣に並ぶため、同じ形だとどちらがどちらか分からない。総合難易度の説明は
`RouteAxisProfile`側（総合難易度の表示の隣、`InfoPopover`）にあり、候補タブごとに
繰り返し表示される。デスクトップは「ルート結果」`Disclosure`の`trailing`、モバイルは
BottomSheetの`headerAction`propとして同じヘルパーを渡す（`routes.length > 0`の間のみ）。
候補タブ列のvalue体系はroute idと`features/route/useRouteResults.ts: COMPARISON_TAB`。

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
地図の上に重ねた操作部品（左のチップ列・右の操作列・上のレンズ・下のまとめて操作する行等）も同じ理由で余白へ足す。
これらは部品の側に「どの辺を覆うか」の印（`mapOverlayEdge`）を付け、`MapView`がフィットする瞬間に印の付いた部品の実寸を
測って、呼び出し側が測った値と辺ごとに大きい方を取る——部品を足す人は印を1つ付ければよく、`page.tsx`の測る関数へ
部品ごとの計算を足さない。印は位置取りを持つ要素（`absolute`で置いた外枠）に付ける。中の小さい要素に付けると、覆う幅を
小さく測る。
