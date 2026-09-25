# ルート設定・結果パネル（frontend）

## 責務

一般ユーザー向けのルート生成条件入力（距離・重み・除外道路）と、生成結果の表示・比較
（軸別内訳・候補一覧・研究モードの実験スロット比較）を担う。

**対象ファイル**

| ファイル | 責務 |
|---|---|
| `features/route/RouteForm/RouteForm.tsx` | 距離スライダー・候補数ステッパー・周回/目的地モード切替の入力欄。「ルート設定」区分の各タブの中身を`Tabs.Content`として並べる（タブ列と選択状態は`page.tsx`、下記参照） |
| `features/route/RouteForm/useRouteFormSubmit.ts` | 上記の検証・送信ロジック（`{error, handleSubmit}`）。「ルート生成」ボタン自体は`RouteForm`の外（`page.tsx`の見出し行）にあるため分離している（下記参照） |
| `features/route/RouteSettingsPanel/RouteSettingsPanel.tsx` | 一般向け軸重み設定（「重み」タブの中身。地図の色分けはここになく`LensControl`のみが持つ、下記参照） |
| `features/route/RouteSettingsPanel/HardFilterPanel.tsx` | 0次ハードフィルタ（「除外」タブの中身）。キー・画面に出す名前・既定値はすべて生成物`route-generate-config.json`（backend `domain/hard_filters.py`）が正で、名前をフロントに持たない——キーと名前を別々に持つと、足したフィルタに名前が無く内部名が出る。重みづけとの違い（通らない）は見出し脇の(i)の奥に置く |
| `features/route/routeWeightShare.ts` | 重み配分の純関数（帯グラフの境界ドラッグ`clampBoundaryDrag`・刻みと上下限） |
| `features/conditions/WindBearingSlider/WindBearingSlider.tsx` | 走行方位の指定コンパスダイヤル（`TravelBearingControl`から使われる。単体としての設置場所は[ページ全体構成・状態管理](page-composition.md)参照） |
| `features/conditions/cardinalLabel.ts` | 角度を8方位の呼び名へ。呼び名の並びはbackend（`domain/geo.py: COMPASS_LABELS`）が配り、丸めはbackendと同じhalf-up——違うと境界の角度でラベルが食い違う |
| `features/route/RouteAxisProfile/RouteAxisProfile.tsx` | 候補ごとのタブの中身（公開軸すべての軸別難易度一覧＋「重み付き寄与度」内訳）。地図の色分けを選ぶ操作はここには無い（`LensControl`）。候補一覧のタブ自体はpage.tsxが直接組み立てる（[ページ全体構成・状態管理](page-composition.md)参照） |
| `features/route/routeTabLabel.ts` | 候補タブの「基準線からの超過時間」を組み立てる純関数（`fastestDurationSeconds`・`extraDurationLabel`）と、区間を乗り換えて作った候補の判定（`isSplicedRoute`・`SPLICED_ROUTE_ID_PREFIX`）。**合成も素の結果と本質的に区別せず**、並び順は生成候補と同じ規約に乗せ（`features/route/routeSplice.ts: insertByDifficulty`）、見分けだけをタブの名前（「合成」）で付ける。**接頭辞はbackendが付ける値で、判定と組み立ての両方がこの1つを使う**——別々に書くと片方だけ変えたときに合成ルートが一覧で見分けられなくなる（型でも例外でも現れない）。タブ列自体はpage.tsxが組み立てる（[ページ全体構成・状態管理](page-composition.md)参照） |
| `features/route/RouteAxisProfile/axisRawValue.ts` | 軸の生値（折れ点を通す前）を単位付きの表示文へ整える純関数（`formatAxisRawValue`）。走行距離を掛けた総量を添えるのは、軸カタログが`raw_value_total_unit`を返した軸だけ——総量が読み手の判断を変えるかの判断はbackendが持ち、フロントは単位の綴りから決めない。単位が定まらない軸の内訳1件を整える`formatMaterialBreakdown`（numeric/boolean）・`formatCategoryBreakdown`（categorical、最も延長の長い値）も持つ |
| `components/AxisContributionBar/AxisContributionBar.tsx` | 「重み付き寄与度」内訳の表示部品（積み上げ1本バー＋凡例）。ルート全体の内訳（RouteAxisProfile）・区間クリック詳細（page.tsx: selectedRouteSegment）の両方から共用する |
| `features/route/ComparisonPanel/ComparisonPanel.tsx`・`types/experimentSlot.ts`（`ExperimentSlot`型・`MAX_EXPERIMENT_SLOTS`） | 研究モードの実験スロット比較表 |
| `hooks/useAxisCatalog.ts` | `GET /api/axis-catalog`取得。軸一覧・既定重み・ramp軸・軸ラベル・二次軸・ルート色分けモードを一括提供 |
| `lib/axisCatalog.ts` | 上記フックが返すカタログを、応答から導く純関数（`axisCatalogFromResponse`）と、画面が読む較正値（`CLIENT_TUNING_IDS`・`clientTuningValue`）。フックが持つのは「いつ取りに行き、誰と共有するか」だけ |
| `services/axisCatalogApi.ts` | 上記フックが叩くbackend APIの薄いラッパー |
| `lib/evaluationAxes.ts` | 重み一覧の1行の型（`PreferenceAxisDef`）と、カタログ1件をそれへ変える唯一の変換（`preferenceAxisFromCatalog`） |
| `features/route/difficultyLoadBar.ts` | 難易度の帯の高さ（`baselineDistanceKm`・`loadBarHeightRatio`・`LOAD_BAR_MAX_HEIGHT_RATIO`）。帯は長さが総合難易度なので、高さへ距離の倍率を与えると塗られた面積が`difficulty_load`、積み上げの色ごとの面積が軸別の負荷になる。基準（高さ1.0）は**一覧の中で最も短い候補**——目標距離やbackendの値から取ると、周回モードと目的地モードで基準の意味が変わり、同じ高さが別のことを指す。距離の比をそのまま高さにすると行が破綻するため上限で頭打ちにし、そのぶん面積は負荷に厳密比例しなくなるので数値を併記する |
| `lib/geoDistance.ts` | 座標列の距離計算（`haversineKm`・`cumulativeDistancesKm`）。区間の位置と代替の距離差を出すのに使う |
| `features/route/routePreferenceSync.ts` | `route_preference`のキー集合をカタログへ同期する共通ロジック |
| `features/route/hardFilterSync.ts` | 保存された`hard_filters`のキー集合を正本（`routeGenerateConfig.hard_filters`）へ整合させる。backendはキー集合の完全一致を要求するため、デプロイでフィルタが増減しても保存値をまたいで送信が成立するようにする |
| `components/ui/FieldLabel/FieldLabel.tsx` | 情報アイコン付きラベルの共有UI部品（値を変えたら上書きをONにする包みは`RouteSettingsPanel.tsx`が持つ） |
| `features/route/SegmentWind/SegmentWind.tsx` | 区間の詳細に出す、その区間の評価に使った風（下記「区間クリック詳細」） |
| `features/route/RouteSplicePanel/RouteSplicePanel.tsx` | 区間の乗り換えの結果面（「ルート結果」が編集モードのときの中身）。**選ぶのは地図、パネルは結果だけ**——地図の破線が「いまの道から乗り換えられる先」・太い実線が「いま作っているルート」で、タップすると乗り換わり、その先の分かれ道が次の破線になる（次に選べる区間は`features/route/routeSplice.ts: buildSplicedShape`が組む「いまの組み合わせ」との差として求めるため、乗り換え先の道の上の分岐もそのまま現れる。候補どうしが同じ地点を通るかはbackendが返すNode id［`node_ids`］で判定し、**当てると一度通った地点へ戻る代替は選択肢に出さない**——backendは連結性しか見ず、折り返しも走れはするため落とさない）。パネルはルート結果と同じ指標（距離・所要・総合難易度・負荷）で元と編集後を**2列×2行**に並べ（1セルに「元→編集後 差」を収め、列見出しを持たない）、軸別は2本並べず**差だけの1本**（中央が0・左が楽になった側・長さが変化量・色は軸チップと同じ）。戻すのは見出し行の「1つ戻す」「全部戻す」で、巻き戻せるのは直前の1手ずつ（適用済みの範囲はその時点の経路に対する位置のため、途中だけは外せない）。`edge_ids`が空の候補では「差が無い」と「そもそも出せない」を区別して伝える。使い方は画面へ書かず見出し脇の(i)の奥に置き、操作（1つ戻す・全部戻す・差分・作成）はパネルの他の操作と同じアイコンの下に名前を置く形 |
| `features/map/scene/groups/routes.ts`（乗り換え帯の箇所） | 他の候補が別の道を通る区間を地図へ帯で描き、**タップでその道を選べる**（`onSpliceStretchSelect`。選ぶ操作の中心を地図へ置く——パネルの行だけで選ばせると、どの行がどの帯かを目で対応づける必要がある。帯と当たり判定は役割`spliceBandLine`・`spliceBandHit`として宣言する）。帯はどれも破線で描く。タップして乗り換えた先は帯ではなく、いま作っているルート（太い実線）の一部として描かれる。破線の刻みは配列で持つ（feature式に依存しない） |
| `features/map/scene/groups/routes.ts` | ルート候補・選択中ルート・区間色分け・乗り換え帯・比較スロットの宣言。状態から載るべきレイヤーの並びを返すだけで、地図を直接は触らない |

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
```

- 軸の一覧・既定重みは`useAxisCatalog`経由（取得完了まで・失敗時は既存軸の静的
  フォールバック）。軸スタジオでの追加が再デプロイなしに反映される。
- 取得に失敗したときの告知はこのパネルにあり、**再試行導線はここにしかない**。影響は
  重み配分だけではない——同じ応答がタイル世代も運ぶため、地図の道路・POI・事故も出ない
  （[静的地図レイヤー](static-map-layers.md)「配信情報を取得できず表示できません」節）。
  告知の文面はその両方を述べる。
- **カタログ1件→`PreferenceAxisDef`の変換は`evaluationAxes.ts: preferenceAxisFromCatalog`
  1本**で、カタログから重み一覧を作る経路はすべてこれを通る——経路ごとに組み立てを
  書くと、片方にだけフィールドを書き足した状態が型検査を通ってしまう
  （`PreferenceAxisDef`のフィールドはすべてoptional）。
- カテゴリ（観測/推定/動的）によるグルーピング表示は行わない。軸スタジオは常に
  `category="推定"`固定で軸を作るため、フラットな1本のリストで表示する。
- **軸が増えてもパネルの高さが変わらない構成**にする（走行中のスマホで扱うため）。
  全軸の取り分は高さ固定の帯グラフ1本に収まり、選択中の軸の行も1行で固定。縦に伸びうるのは
  軸チップの領域だけで、そこは高さ上限＋内部スクロールを持つ（`legendRow`）。チップは
  **有効な軸を先に並べる**ため、スクロールせずに現在の配分を読める。
- 帯グラフの区間には、幅が許すぶんだけ軸アイコンと%を入れる（`SEGMENT_ICON_MIN_PCT`・
  `SEGMENT_VALUE_MIN_PCT`。狭い区間は%のみ→何も出さない、の順に落とす）。区間に入らない
  軸の%もチップ側では必ず読める。設定側の帯は区間そのものが操作対象で高さが要るため、
  結果パネル側の細い帯（`ui/AxisLegend`の`stackBarClass`）とはスタイルを共有しない。
- 重み配分バー（帯グラフ、`stackBarOuter`/`stackBarHandle`）は表示専用ではなく、
  隣り合う2区間の境界（`role="slider"`のハンドル、幅16px）をポインタドラッグまたは
  矢印キーで操作すると、その両隣の2軸間でだけ重みが移動する（他の軸・2軸の合計は
  変わらない、`clampBoundaryDrag`が範囲[`WEIGHT_STEP`, 0.6]内へクランプする）。
  ハンドル自身だけに`touch-action: none`を絞ってあり、帯グラフの他の部分（セグメント
  本体）はスクロールジェスチャーを妨げない。**重みの調整手段はこの帯グラフの
  ドラッグ・矢印キー操作のみ**。ドラッグ中の値は帯の区間とチップの%がその場で動いて
  示すため、操作の説明文も、同じ調整を別の形で用意した操作（増減ボタン等）も置かない。
  帯の色と凡例チップの色ドットは、どちらも軸カタログが1回だけ導く識別色
  （`lib/axisCatalog.ts`の`axisColors`、実際の軸数でHSL色相環を等分）を読むため、常に一致する
  （ルート結果・レンズの選択肢も同じ色）。**帯そのものが「重み配分」で
  あり「全体で100%」であることを示すため、タブは見出しも合計の表記も持たない**（言い換えの
  行を置かない、設計原則「冗長なものは削る」）。
- 軸の凡例チップ（`renderLegendChip`）は「本体（アイコン＋略名＋現在の%。タップで
  有効/無効を切替、weight>0が有効の判定基準）」「(i)説明文ポップオーバー」の2要素で構成
  される複合ボタン群。無効な軸（weight=0）はチップ全体を半透明にし、%は出さない。
  軸の説明は画面へ書かずこの(i)の奥に置く（設計原則「冗長なものは削る」）。`route_preference`の
  重みを切り替えるだけで、地図の色分けとは無関係（地図の色分け（レンズ）はこのパネルには
  なく、地図上の`LensControl`だけが持つ）。
- 向きコンパス（`WindBearingSlider`）はこのパネルには存在しない。風・勾配の走行方位は
  `page.tsx`の単一共有state（`travelBearingDeg`）を地図上の`TravelBearingControl`
  1箇所からのみ設定する（[ページ全体構成・状態管理](page-composition.md)「動的材料
  （風・勾配）の状態別表現契約」参照）。
- `routePreference`（送信対象）とカタログのキー集合を`syncRoutePreferenceKeys`で
  双方向同期する（軸の追加/unpublishに追従。backendは「上書きするなら既知の全axis_id
  キー一致」を要求するため、ズレるとルート生成が422になる）。
- 除外する道路（0次フィルタ）は独立したタブ（`HardFilterPanel`）に置く。重みづけと違い
  「通らない」指定であることを本文で明示し、将来の除外条件もこのタブへ足す。既定値から
  変更済みのときだけ、そのタブ内に戻すボタンを出す。
- 重みを既定値へ戻す操作はこのタブに持たない。名前を付けた配分の切り替え（プロファイル）の1つとして扱う。

**暗黙の前提**: `useAxisCatalog()`は`page.tsx`と`RouteSettingsPanel.tsx`から同時に呼ばれうる
（`page.tsx`がマウントした時点で子の`RouteSettingsPanel`も同時マウントされるため）。
解決済みのカタログはモジュールレベルの単一ストア（`useSyncExternalStore`）として持ち、
全呼び出し元が同じオブジェクト参照を購読するため、どちらか一方のフェッチが解決すれば
両方の呼び出し元へ即座に反映される（2インスタンス間で`axes`配列が食い違うことは
構造的に起こらない）。同時に飛んでいる（未解決の）フェッチはモジュールレベル変数
`inFlightCatalogFetch`で重複排除する。永続キャッシュはしない（軸スタジオでの公開操作を
再デプロイなしに反映するため、後続の別マウント[モバイルのBottomSheetを開き直す等]では
改めて最新を取得する）が、フェッチ失敗時は取得済みの正常なカタログを巻き戻さない
（他の呼び出し元が既に取得していれば、失敗した側の再フェッチはストアを書き換えない）。

**暗黙の前提（`loaded`フラグの意味）**: `AxisCatalog.loaded`は「取得成功し他フィールドが
実際のDB由来の値であること」を表す。`loaded=false`（未取得/失敗）の間は軸が0件のため、「軸スタジオの現在の
公開軸集合と一致していなければならない」処理（`route_preference`のキー整合等）ではこのフラグで
未確定状態を区別しなければならない——区別しないと「公開軸が1つも無い」と読み、保存済みの重みを
全部消す。取得成功時に軸が0件（全軸非公開）であっても`loaded=true`になる
（0件も確定した実際の状態のため）。

`loaded`と対になる`failed`は「取得を試みて失敗し、まだ一度も成功していない」を表す
（未取得=両方false／成功=`loaded`のみ／失敗=`failed`のみ）。この状態でも重み配分は
編集できてしまうが、`page.tsx: handleGenerate`は`loaded`ガードにより`route_preference`と
`lens_axis_id`を送らず、backendの既定配分で探索される。黙って捨てると「重みを変えたのに
結果が変わらない」を実験の差だと取り違えるため、`RouteSettingsPanel`が失敗の表示と
再試行導線（`retryAxisCatalogFetch`、成功済みなら何もしない）を出す。

`lens_axis_id`にも同じガードを掛ける。**存在しない軸idはエラーにならず黙って無視される**
ため、送ってしまうと「選んだ軸で塗られない」が手掛かり無しで起きる。

## WindBearingSlider.tsx（走行方位ダイヤル）／TravelBearingControl.tsx（地図上の入口）

外部ライブラリを使わない自前実装のコンパス型UI。中心から伸びる矢印
（`components/ui/icons/icons.tsx: WindDirectionArrowIcon`）を直接つかんで回すダイヤルで、矢印自体が
指す向きがそのまま値になる。`value`/`onChange`/`ariaLabel`のみを扱う汎用コンポーネントで、
時刻には一切関与しない（時刻は条件バー`RideConditionBar`の出発時刻が担当）。

`WindBearingSlider`自体は本コンポーネント表に無い`features/conditions/TravelBearingControl/
TravelBearingControl.tsx`（`page.tsx`から直接importされ地図上に置かれるアイコンボタン）
1箇所だけからマウントされる。`page.tsx`の単一共有state`travelBearingDeg`（風・勾配で
共有、[ページ全体構成・状態管理](page-composition.md)「動的材料（風・勾配）の状態別
表現契約」参照）を`TravelBearingControl`が受け取り、地図右上（MapLibreのズーム+/−・
回転コントロールの直下）のアイコンボタンをトリガーにしたRadix Popoverの中で
`WindBearingSlider`を開閉する。出発時刻・想定速度と同じ走行条件の一部として常時表示する
（風・勾配の表示状態に依存しない）。

`cardinalLabel(bearingDeg)`（角度→方位の日本語ラベル）は、呼び名の並びを生成物
（`mapDisplay.compassLabels`、源泉は`backend/app/domain/geo.py: COMPASS_LABELS`）から読み、区分の幅は
その数から決める。丸め方だけを画面側に持ち、backendと同じhalf-upにする（違うと区分の境界で食い違う）。

角度計算・ドラッグ処理は`RouteSettingsPanel.tsx: startBoundaryDrag`（帯グラフの境界
ドラッグ）と同じ「pointerdown起点でwindowへ直接pointermove/upを登録する」パターンを
踏襲する（pointer captureが環境によって確実に効くとは限らないため使わない、という同じ
理由）。ダイヤル自体（矢印の余白を含む円全体）が当たり判定になり、円のどこを触っても
ドラッグを開始できる——特定の小さなノブや細いリングを狙う必要が無い。矢印のタップ位置を
即座に値へ反映する（tap-to-set）ため、ドラッグ開始の初動から値が動く。矢印キー
（`KEY_STEP_DEG`単位）でのキーボード操作にも対応する。`WindBearingSlider.test.tsx`がキーボード操作・
読み上げと、押した点・ドラッグから角度への換算を見る（happy-domは実寸を返さないので、ダイヤルの
`getBoundingClientRect()`だけを差し替える）。

## RouteAxisProfile.tsx（候補ごとタブの中身: 総合難易度＋軸別内訳）

page.tsx（[ページ全体構成・状態管理](page-composition.md)参照）が組み立てる候補ごとの
タブ（方向・距離のみを表示。総合難易度の点数はタブ内では繰り返さない）の中身として、
候補1件につき1つ表示する。呼び出し側（page.tsx）は`axes`へ公開軸すべてを渡す——重み0の軸を
落とすと、下記の「未使用の軸」行（この候補を評価した重みが0だった軸が何本あるかを示す）が
構造的に出せなくなる。

**軸を1行ずつ並べる一覧は持たない**。軸ごとの詳細（軸別難易度・生値・材料内訳・説明）は
寄与度バーの凡例チップを押して開く。1軸1行の一覧は公開軸の本数ぶん縦へ伸びるのに対し、
チップは行内で折り返すため、軸が増えても縦は折り返しぶんしか伸びない。

- **軸の詳細（凡例チップから開く）**: 中身は軸別難易度（`RouteCandidate.axis_difficulties`、
  四捨五入、重みを掛ける前）＋生値＋材料内訳＋軸の説明。**チップの数字（重み付き寄与度）とは
  別の値**であることが分かるよう「軸別難易度 N/100」と単位付きで書く。寄与度バーの凡例
  （`AxisContributionBar`の`renderDetail`）と、下記の「寄与が出ていない軸」のチップの
  どちらから開いても同じ中身を出す（軸の詳細の出どころは1つ）。押せることは
  チップ内の(i)アイコンで示す——このアプリで「押すと説明が出る」を表す形を共有する。
- **評価に使っていない軸**: 重み（生成時点の`route_preference`）が0の軸のチップは**出さない**
  ——軸の一覧はルート設定側が持ち、結果側は「このルートの評価に効いた軸」に絞る。チップの形は
  ルート設定パネルの「重み配分」と共有する（`ui/AxisLegend`）——同じ軸が画面に
  よって違う形・違う色に見えると、設定した軸と結果に出ている軸が同じものだと読み取れない。
  重みは入っているのに値が来ない軸のチップは押せるままで、詳細が「データなし」を示す。
- **生値（詳細の中）**: 折れ点を通す前の生値を詳細へ単位付きで出す
  （`RouteCandidate.axis_raw_values` × `AxisCatalogEntry.raw_value_unit`、
  `axisRawValue.ts: formatAxisRawValue`）。候補の走行距離を掛けた総量も続ける
  （例:「0.8回/km・約26回」）——ただし**総量が読み手の判断を変える軸だけ**で、その判断は
  `AxisCatalogEntry.raw_value_total_unit`が持つ（「約3322度曲がる」には比べる尺度が無い）。得点0-100は目盛りの引き方に依存する相対評価
  でしかなく、それだけでは軸単体で経路の良し悪しを判断できないため
  （[設計原則](../../architecture/design-principles.md)11）。
- **内訳（詳細の中）**: 材料まで分解した絶対量を「この軸の内訳: ...」として全件出す
  （`AxisCatalogEntry.material_breakdown` × `RouteCandidate.material_values`、
  `axisRawValue.ts: formatMaterialBreakdown`）。
  表記は材料の型で決まり、軸ごとの対応表を持たない——numericは距離加重平均＋単位
  （「制限速度 42km/h」）、booleanは該当区間の延長割合（「街灯あり 68%」。値が0/1で
  運ばれるため平均がそのまま割合になる）、categoricalは**最も延長の長い値**のラベルと割合
  （「住宅街の道 62%」、`RouteCandidate.material_category_shares` ×
  `AxisCatalogEntry.material_breakdown[].value_labels`、`formatCategoryBreakdown`）。
  categoricalで2件目以降を出さないのは、「幹線道路が◯%」のように複数の値をまとめるには
  どの値を幹線とみなすかという判断表が要り、それをフロントが持つと軸を1本足すたびに表の
  更新が要る状態へ戻るため。ラベルはbackendが返す対訳を引き、未登録の値はタグ生値のまま
  出す。**並べ替えはしない**: 受け取った並びをそのまま使う（順序は配る側が決める）。
  値が来ない材料（categorical材料は数値列に載らない）は飛ばす。
- **負荷（難易度×距離）**: `RouteCandidate.difficulty_load`を総合難易度の隣へ併記する
  （(i)で意味を説明する）。総合難易度が距離で正規化された平均であるのに対しこちらは総量で、
  「難所を通っても短いルート」と「遠回りで易しいルート」を見比べるための値
  （[評価・スコアリング](../backend/evaluation-scoring.md)「ルート単位の集約」節参照）。
  候補の並び順には影響しない。**数値と併せて、下の内訳バーが面積で同じことを表す**
  （下記`AxisContributionBar.tsx`）——負荷は総合難易度に距離を掛けただけの派生量のため、
  独立した数値として並べるだけでは平均と総量の関係が読めない。
- **総合難易度**: `RouteCandidate.overall_difficulty`（絶対基準0-100の軸重み付き合成値）を
  表示する。下記内訳の合計そのものであり、内訳の1項目としては扱わない。候補タブの並び順
  もこの値の昇順（backend `route_generator.py`が返す`routes`配列の並び順をそのまま使う、
  [ページ全体構成・状態管理](page-composition.md)参照）。数字の隣に(i)説明ポップオーバー
  （このコンポーネント自身が持つ、負荷の説明と同じ形）を置く。
- **軸別内訳（重み付き寄与度）**: `RouteCandidate.axis_contributions`（axis_id→重み付き
  寄与度0-100、backend側で区間ごとの合成に使ったのと同じ重み配分を軸別に分解しルート
  全体へ距離加重平均で集約した値。評価できなかった軸（データ欠損）はキー自体が無く非表示。
  重み0の軸はキー自体は残り値が常に0.0になる（backend:
  `domain/evaluation.py: axis_contributions_at_row`参照。frontend側で値0を除外する、
  下記`AxisContributionBar.tsx`参照）を、「総合難易度」の数字の
  隣に`AxisContributionBar`（積み上げ1本バー＋その下の凡例）でそのまま表示する。バーの
  高さには`features/route/difficultyLoadBar.ts: loadBarHeightRatio`が返す距離の倍率を渡す（基準は
  一覧の中で最も短い候補。`page.tsx`が一覧の行と同じ基準で計算して渡す）。合計が
  丸め誤差を除いて`overall_difficulty`と数学的に一致するため、frontend側での独自の
  重み計算は行わない。バーの各セグメントの色は`axisColors`（地図色分けチップと同じ配色）、
  幅は寄与度の値そのもの。
- **凡例の表示設定**: `legendTrigger`（見出し脇の(i)アイコン→ポップオーバー
  でチェックボックス一覧）で、選択中モードの凡例カテゴリを地図上で表示/非表示できる。

## AxisContributionBar.tsx（「重み付き寄与度」の共有表示部品）

「重み配分」帯グラフと同じ表現（`ui/AxisLegend`）の積み上げ1本バーと、その下の凡例（軸アイコン＋数値）を
描画する。**凡例は軸の名前を文字で出さない**——狭い幅では名前がそのまま行数になり、
公開軸の本数ぶんで内訳が画面の大半を占める。軸はアイコン（`axisIconFor`で地図チップと
同じ意匠を引く）で示し、名前は押して開く説明と、押せないチップの`aria-label`が持つ。
軸を選ぶ側（`RouteSettingsPanel`の「重み配分」）は名前が要るため、そちらは同じアイコンに
略名（`chip_label`、最大4文字）を添える。`axes`（表示順・ラベル）・`contributions`（axis_id→寄与度）・`axisColors`のみを
受け取る汎用コンポーネントで、値の出どころ（ルート全体か特定の区間か）を一切知らない。
`contributions`にキーが無い軸・値が0の軸（重み0の軸は常にこの値になる）は自動的に
除外されるため、呼び出し側は`axes`を絞り込まずに渡してよい。

凡例に並べる軸は`legendAxes`で差し替えられる（省略時は帯グラフに出る軸だけ）。公開軸
すべてを渡せば、寄与が出ない軸も凡例に残る。

**軸の並び順に連続的な意味は無い。** 軸を横に並べて見せるUIでは、隣り合う軸の間に傾き・
推移があるように見せない——値どうしを線やグラデーションでつなぐと、「隣の軸へ向かって
増えている」という読み方が生まれる。高低は各軸の中だけで示す（色と長さ）。

チップを詳細の入口にするかは`renderDetail`（軸→詳細の中身）が決める。prop自体を省略すれば
どのチップも押せない静的な凡例になる。**`renderDetail`を渡したうえで軸ごとにnullを返すと、
その軸は凡例から落ちる**（結果パネルは重み0の軸でnullを返しており、評価に使っていない軸は
並ばない）。**詳細の中身はこのコンポーネントが組み立てない**
——軸別難易度も材料値も呼び出し側が持つデータであり、ここが知ると値の出どころを知らない
という前提が崩れる。
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
時刻・評価に使った風（`SegmentWind`: 予報の時刻・風向風速、予報を追える範囲の先で延ばして使った区間はその旨。
(i)の説明がレグごとに追う時間を生成物`route-generate-config.json`の`wind_forecast_hours_per_leg`から出す）＋
`AxisContributionBar`（区間の`axis_contributions`）を表示し、×ボタンで
`selectedRouteSegment`をnullへ戻すとルート全体表示に復帰する。研究モード
（`researchEnabled`）の間だけ、`AxisContributionBar`の下へ区間の材料値
（`RouteSegmentDetail.material_values`）の一覧を追加表示する——一般ユーザー向けには
出さない（走行中のスマホ利用が主で情報量を増やしたくないという方針、ComparisonPanel.tsxの
材料値行と同じ`lib/axisMaterialsCatalog.ts: materialCatalogName`/`formatMaterialValue`を使う。名前を引けない材料は出さない）。

## ComparisonPanel.tsx

- 研究モードの実験スロット比較表。表示順は
  (1) ルート属性（距離・獲得標高。材料ではないため`material_values`には乗らない固定行）→
  (2) 材料値の行（`RouteCandidate.material_values`から動的生成。重み>0の軸が参照する
  材料id→値の辞書で、いずれかのスロットが値を持つ材料だけを行にする。ラベル・単位は
  `materials`[page.tsxが`useMaterialCatalog()`を渡す]から引く。**行見出しは論理名だけ**
  （`materialCatalogName`）——物理名まで併記するのは材料を選ぶ軸スタジオの都合で、読むだけの
  この表では見出しが横へ伸びて値の列を画面外へ押し出す）→
  (3) 軸ごとの難易度の行（`axisLabels`・`axes`をpage.tsxから受け取り、
  `RouteCandidate.axis_difficulties`から動的生成。軸スタジオの軸増減に自動追従する）→
  (4) 全軸合成の総合難易度（`overall_difficulty`、末尾固定）。各列は各回の
  `ExperimentSlot.topCandidate`（生成直後の`overall_difficulty`最小候補で固定、
  [ページ全体構成・状態管理](page-composition.md)参照）。page.tsxが渡す`axes`は、
  表示中のいずれかの実験スロットで生成時点の重み（`ExperimentSlot.conditions.
  route_preference`）が>0だった軸に絞り込み済み——現在のライブな`routePreference`
  （「今」の設定）は使わない。
- **比べる相手がいない間は表の代わりに案内を出す**（スロット0件・1件）。`null`を返すと
  タブの下が空白になり、壊れているように見える。
- 生成が成功したら比較タブから候補タブへ戻す（`page.tsx: handleGenerate`が
  `comparisonTabActive`を倒す）——押した操作の結果が見えないまま前回までの比較表が残ると、
  生成が効かなかったように見える。

## 生成を待つ時間・投げる回数の根拠

**ポーリングの打ち切り（`features/route/routeApi.ts: MAX_POLL_DURATION_MS`）は、冷パスの総所要時間を
安全マージン込みで上回る値にする。** 値はフロントに書かず、backendがジョブの結果を持つ時間
（`infrastructure/job_registry.py: JOB_TTL_SECONDS`）を生成物`route-generate-config.json`経由で
そのまま使う——保持時間より長く待つと、掃除済みのjob_idを引いて結果の代わりに404を見る。
動かすときはbackendの宣言を変える。根拠となる最悪ケースは2つあり、**両方**を上回ること。

| 測った環境 | 最悪ケース |
|---|---|
| 本番 | 都心30km・未split（`save_graph`のバルクUPSERT込み）で約316秒 |
| 開発機 | 都心部で`prepare_ms`=約356秒・`total_ms`=約361秒 |

開発機は資源競合で本番より悪化するが、**同種の遅さ自体は本番でも再現する**。片方だけを見て
詰めると、もう片方の環境で「生成できるのに打ち切られる」が起きる。DBの
`ROUTE_GENERATION_COMMAND_TIMEOUT_SECONDS`はクエリ1本ごとの上限で、この値とは独立。

**差分プレビューを自動で走らせず、押したときだけ投げる。** 評価はbackendでしか出せず
（[design-principles.md](../../architecture/design-principles.md)構造仕様10）、かつ
**生成APIにはレート上限（1分あたり10回）がある**ため、選んでいる途中の組み合わせごとに
投げると上限へ当たる。選び終えてから押す形にし、同じ組み合わせの結果は覚えて投げ直さない。

## RouteForm.tsx・useRouteFormSubmit.ts

`RouteMode`（"loop"|"destination"）で周回/目的地モードを切り替える入力欄一式
（`RouteForm.tsx`）と、その検証・送信ロジック（`useRouteFormSubmit.ts`）を分離する。
デスクトップ・モバイルとも「ルート設定」区分（`RouteSettingsPanel`と同じ場所）から呼ぶ。

「ルート設定」区分自体を「条件」（`RouteForm`のモード切替・距離・候補数）・
「重み」（`weightsPanel`propで受け取る`RouteSettingsPanel`一式）・
「除外」（`exclusionsPanel`prop、`HardFilterPanel`）のタブへ分ける。
**タブ列（`Tabs.List`）は見出し行の左（見出しのすぐ右）に置き、タブの中身
（`Tabs.Content`）は本文に出る**ため、
両方を囲む`Tabs.Root`（`@radix-ui/react-tabs`）と選択状態は`page.tsx`が持つ
（`RouteForm`は中身だけを描く）。タブ専用の行を作らないぶん本文の縦が空き、ラベルは
2文字へ詰める。どのタブも`forceMount`で常時マウントし表示だけ`data-state`で切り替える
（`RouteSettingsPanel`がローカルstate[`lastWeights`等]を持つため、タブ切替のたびに
アンマウントすると失われる。ルート結果のタブと同じ方式）。
「ルート生成」ボタンも同じ見出し行の**右端**に置く（デスクトップは`Disclosure`の`trailing`
の中で左右へ分け、モバイルはタブを`BottomSheet`の`headerLead`・ボタンを`headerAction`へ
渡す）。中身を切り替えるタブと、押して生成を走らせるボタンは役割が違うため、行の中でも
離し、タブは下線型・ボタンは塗りと見た目でも分ける（「ルート結果」見出し行の
`renderRouteResultHeaderActions`と
同じ場所）にあり、どのタブを見ていても押せる（`page.tsx: renderRouteSectionHeaderActions`）。検証エラーは本文でもボタンの隣でもなく
「ルート結果」欄へ出す（[page-composition.md](page-composition.md)の「生成に関する
フィードバックの置き場」参照）。同じ見出し行には、生成条件が表示中の候補とずれている間だけ
印（`conditionsDirty`）を出す——条件を変えている本人は設定側を見ているため。検証・送信ロジック自体は
`useRouteFormSubmit`（`distance`・`maxRoutes`・`routeMode`・`waypointCount`・
`destinationSet`・`onGenerate`を受け取り`{error, handleSubmit}`を返す）へ切り出し、
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
候補数ステッパーはbackendの決まった数〔`fixedRouteCount`〕を出して押せなくなり、その間も
string stateとして残り続ける値に対する境界チェック）向けに残っている。目的地モードでは距離入力を出さない。想定速度はこの
フォームでは扱わない（地図右上の条件アイコン列`RideConditionBar`、page-composition.md参照）。
候補数ステッパーは**モード切替と同じ行**に置く（どちらのモードでも効く共通の条件で、
モードごとの入力［距離／地点］とは階層が違う。モードごとの中身の下に置くと、モードに
属する条件に見えるうえ1行ぶん縦を余計に使う）。経由地があるときは**消さずに押せない状態で残す**（値は「1件」、理由は隣の(i)の奥）——
この条件では候補件数の指定が効かないため操作しても無駄だが、消えると壊れて見える。経由地・目的地のいずれも未指定のまま
生成しようとするとサイレント失敗せずエラー文言を出す。

### 地点の指定（出発地・経由地・目的地）

3つとも役割は同じ「地点を置く」ため、**同じ形の行**を縦に並べる（`renderPointRow`）。行頭の
印は地図のマーカーと同じ色・同じ字で、行とピンを見た目で結ぶ。行には現在の値（現在地／
地図で指定／なし／N地点／未設定）が出るため、**地図を見に行かなくても何が決まっているかが
読める**。

- 地図のピンは3つとも同じ丸いバッジ（`MapView.tsx: createPointMarkerElement`、出発地だけは
  現在地アイコン入りの白バッジ）で、**どれもつかんで動かせる**。**行頭の印と地図のピンは
  同じ図形を使う**（`lib/mapDisplay/pinMarks.ts`が中身と背景色を持ち、地図側はMarkerへ渡す生のDOM、
  パネル側はその文字列をそのまま描く）——同じものを2箇所で描くと、片方だけ直したときに
  行とピンが違う見た目になる。動かした直後のclickは読み飛ばす（`bindDragAwareClick`）——同じ操作の
  終わりにclickが飛ぶため、動かしただけで削除・解除が起きてしまう。
- **行そのものが押下領域**（`pointMain`）。押す場所を探させず、行の幅も詰まる。解除（✕）と
  「現在地に戻す」は別の操作のため、入れ子にせず行の外側へ並べる。
- **地図でできることは、いま見ているパネルが持つ操作だけにする**。「ルート設定」の条件タブ＝
  地点を置く・つかんで動かす・消す（`pointEditingEnabled`）、「ルート結果」＝候補の切り替えと
  区間詳細（`routeInspectionEnabled`）、「ルート編集」＝乗り換え先の選択だけで元ルートは固定。
  地図を触った副作用で、いま見ていない面の状態が変わらないようにする。道路・POI等の
  ポップアップは地図そのものを読む機能のため、この区分の対象外（ルートの状態を変えない）。
- **置ける状態は常に1つだけ**。`PinRole`（"origin"|"waypoint"|"destination"）のうち武装中の
  1つを`page.tsx`が持ち、その間だけ地図のタップがピンの配置になる（`MapView`の
  `armedPinRole`・`onPinPlace`）。**武装していなければ地図を触ってもピンは増えない**——役割を
  選ばずに置けると、地図を見ているだけのつもりの操作で経由地が増える。
- 出発地の行にも操作が出るため、**動かせること自体が画面に現れる**（地図のマーカーを
  ドラッグしても動かせるが、それだけだと画面に手掛かりが無い）。置いたあとは「現在地に戻す」
  が出て、現在地の取得（`useLocation: handleLocateMe`）がその役割を兼ねる。
- 経由地だけは置いたあとも武装を続ける（続けて何地点も置くのが普通の使い方で、1つ置くたびに
  押し直させない）。武装中も件数と解除（✕）は出したままにする。
- 設定済みの地点から武装しても値は残る。次の地図タップが置き換えになる——生成後に目的地を
  変えたいとき、解除してから指定し直す2段階を踏ませないため。解除は行の✕が担う。
- 目的地モードへ切り替えた時点で目的地・経由地とも未指定なら、行を押さなくても目的地を
  置ける状態にする（`page.tsx: handleRouteModeChange`）。既に目的地・経由地がある場合は
  自動で武装しない——次のタップの意図が「経由地の追加」である可能性があり、武装したままだと
  意図せず目的地が上書きされてしまうため。
- 置ける場所も限る。「ルート設定」区分を見ていて、かつ「条件」タブを開いている間だけ武装が
  効く（`page.tsx: pinPlacementArmedRole`）。「ルート結果」を見ている間や他のタブを開いて
  いる間は、武装したままでも地図のタップはピンにしない。
