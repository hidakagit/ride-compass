# codereview レビュー（2026-09-01）

## 対象

- 対象コミット: `512a089`（T518完了コミット、親は`3378498^`）
- 差分範囲: T518「ルート結果パネルの再構成」実装。`git diff 3378498^..512a089 -- <対象13ファイル>`
  （`frontend/src/app/page.tsx`・`frontend/src/components/Map/MapView.tsx`・
  `MapView.routes.test.ts`・`RouteAxisProfile/`一式・`RouteSettingsPanel.tsx`・
  docs 6ファイル）
- レビュー種別: `codereview`（`/code-review`、high effort、3+5角度×6候補→1票検証→上位10件）
- 実施方法: 8つの独立した観点別Agent（correctness×3・reuse・simplification・
  efficiency・altitude・conventions）を並行実行し、収集した候補のうち高確度のものを
  実コードの直接確認で裏取りした。
- **対応状況（2026-09-01追記）**: [T524](../../../docs/tasks/T524.md)として起票・
  完了。全17件のうち11件修正、2件（比較タブの軸フィルタ基準・内訳合計の精度）は
  ユーザー確認のうえ設計変更、4件は理由付きで見送り（未使用依存削除は別セッションの
  package.json並行編集を避けたため、legend系の2件はライブ検証困難な状況下での
  UIリスク回避、内訳バーの視覚表現はレビュー時点でも既にDEFER指定、型キャストと
  useAxisCatalog複数インスタンスの2件はConfidence Lowのため）。詳細はT524.md参照。

## Executive Summary

correctness角度（A/B/C）とaltitude角度が**独立に同じ2箇所**（MapView.tsxの
`redrawAllLayers`・RouteAxisProfile.tsxの早期return）へ収束しており、いずれも
実コード確認で再現条件を確認済み。T518自体が「『ルート』チップOFFで完全非表示にする」
「全体プロファイルを統合してもチップ・凡例設定への到達性を落とさない」という2つの
不変条件を新設したPRであるにもかかわらず、その不変条件を守れていない経路が2つ
（スタイル再読み込み・軸データ0件の候補選択）残っている。単体テストは新設した
`drawBaseRoutes`/`hideBaseRoutes`等の関数を単体で叩いているため、これらの経路
（`redrawAllLayers`からの呼び出し・`RouteAxisProfile`の早期return分岐）はカバーして
いない。

## Findings

### [P1] `redrawAllLayers`が`routeLayerOn`を見ずに候補線・ハロー・矢印を強制再表示する

- Problem: 地図スタイル再読み込み（「地図データを再読み込み」ボタン、
  `refreshToken`変更→`map.setStyle()`→`style.load`→`redrawAllLayers`）が走ると、
  「ルート」チップをOFFにして隠したはずの候補線・選択中候補のハロー・方向矢印が
  復活する。T518がまさに解消しようとした不整合（チップOFFなのに一部レイヤーだけ
  出続ける）が、別の経路から再発している。
- Evidence: `frontend/src/components/Map/MapView.tsx:2491-2591`の`redrawAllLayers`は
  `redrawPropsRef.current`から`routeLayerOn`を**destructureして持っている**
  （2495行目）にもかかわらず、2580-2582行の`drawBaseRoutes(map, routes,
  selectedRouteId)`・`drawSelectedOutline(map, routes, selectedRouteId)`は
  `routeLayerOn`を一切参照せず無条件に呼ばれる。直後2586行の
  `if (routeLayerOn && selected?.segments) drawDetailSegments(...) else
  hideDetailSegments(map)`は正しく分岐しており、3レイヤーグループのうち
  detail-segmentsだけが対称的に扱われている。T518のdrawBaseRoutes/drawSelectedOutline
  自体は`setLayerVisibility(..., true)`を内部で強制するよう変更済み
  （MapView.tsx:851, 898-900）のため、この無条件呼び出しは単なるno-opではなく
  実際にvisibility=trueへ書き換える。
- Impact: 「ルート」チップOFFの状態でベースマップ切替・「地図データを再読み込み」・
  テーマ切替等の`map.setStyle()`を伴う操作を行うと、候補線・ハロー・方向矢印が
  黙って再表示される（色分けレイヤーだけは`routeLayerOn`のままhideDetailSegmentsで
  非表示を維持するため、「線は出るが色は無い」という中途半端な表示になる）。
- Root Cause: T518は「ルート」チップの表示切替を効かせる箇所を、新設した2つの
  `useEffect`（`[routes, selectedRouteId, routeLayerOn]`依存）にのみ実装し、
  既存の第3の呼び出し元である`redrawAllLayers`（スタイル再構築専用の再描画経路）を
  見落とした。3箇所（2つのeffect＋redrawAllLayers）がそれぞれ独立に
  `routeLayerOn`を参照する設計になっており、1箇所の追従漏れが起きやすい。
- Recommendation: `redrawAllLayers`の2580-2582行を、2586行と同じ
  `if (routeLayerOn) { drawBaseRoutes(...); drawSelectedOutline(...); } else {
  hideBaseRoutes(map); hideSelectedOutline(map); }`へ揃える。根本対応としては、
  「ルート」チップが制御する5レイヤー（候補線・ハロー・矢印ハロー・矢印・
  detail-segments）のIDを1つの配列にまとめ、`routeLayerOn`から1回の関数で
  一括して表示/非表示を切り替える汎用機構（既存の`setStaticOverlayVisibility`と
  同じ設計、`MapView.tsx:1845`）へ寄せれば、4つ目の関連レイヤーが増えても
  呼び出し元を1つ増やすだけで済み、今回のような見落としが構造的に起きなくなる。
- Scope: S（応急修正のみなら2580-2582行の分岐追加、数行）／M（汎用機構化まで含めると）
- Confidence: High（コードで確認済み。correctness角度A・B・Cとaltitude角度の4つの
  独立エージェントが同一箇所へ収束し、実ファイルの直接確認でも再現条件を確認した）

### [P1] `RouteAxisProfile`の早期returnが、内訳だけでなく地図色分けチップ・凡例設定ごと隠す

- Problem: 選択中候補の`axis_difficulties`に、表示対象の軸（重み>0）のキーが
  1つも無い場合、`RouteAxisProfile`全体が「このルートで表示できる評価軸データが
  ありません」の1行だけになる。統合前は独立していた「地図の色分け」チップ列・
  「凡例の表示設定」ポップオーバーもこの中に含まれているため、同じ条件で丸ごと
  失われる。
- Evidence: `frontend/src/components/RouteAxisProfile/RouteAxisProfile.tsx`の
  `const rows = axes.filter((axis) => axisDifficulties[axis.axisId] != null);`の
  直後にある`if (rows.length === 0) { return <p>...</p>; }`が、その後に続く
  「地図の色分け」チップ列・「合計」・「内訳」・凡例ポップオーバーをまとめて含む
  `<div className={styles.wrap}>`より**前**にある。旧`renderRouteColorSectionBody`
  （削除済み、page.tsxの`git diff`参照）は`if (!hasDetail) return null;`だけを
  ガードにしており、`axisDifficulties`の中身とは無関係に色分け選択・凡例設定を
  出していた。
- Impact: 重み>0の軸をすべて限定的な軸（例: データが疎なエリアでsurface_q系のみに
  重みを寄せる等）へ絞った状態で、その軸のデータが当該候補に無い場合、
  「総合難易度」チップ（`routeStyleModeId`を戻す唯一のUI導線）にも、凡例カテゴリの
  表示/非表示トグルにも到達できなくなる。
- Root Cause: 統合時に、旧・独立ブロックが持っていた「`hasDetail`さえ立てば出す」
  という緩いゲートを、新設コンポーネントの「表示する軸データが1件も無ければ
  空状態文言のみ」という厳しいガードへそのまま流用してしまった。
- Recommendation: 早期returnを内訳リスト部分（`.breakdown`のul）だけに限定し、
  「地図の色分け」チップ列・凡例ポップオーバーは`rows.length === 0`でも表示を
  維持する（内訳が空状態文言になるだけで、色分け操作自体は独立して機能させる）。
- Scope: S（JSXの早期return位置をずらすだけ）
- Confidence: High（構造はdiffから直接確認済み。correctness角度A・B・Cの3エージェントが
  独立に同一箇所を指摘）

### [P2] 候補選択直後（`hasDetail`成立前）に地図「ルート」チップが無効化されたまま、内訳チップ経由でONにできてしまう

- Problem: `selectedCandidate`はあるが`segments`未取得（`hasDetail=false`）の間、
  地図上の「ルート」チップは無効化表示（title「ルートを生成・選択すると使えます」）
  だが、同じタイミングで表示される`RouteAxisProfile`のチップは操作可能で、
  クリックすると`layerVisibility.route`をONへ変える。
- Evidence: `frontend/src/app/page.tsx:620`
  `const hasDetail = !!selectedCandidate?.segments && selectedCandidate.segments.length > 0;`。
  `page.tsx:933`
  `const disabledReason = layer.id === "route" && !hasDetail ? "ルートを生成・選択すると使えます" : null;`
  （地図チップの無効化条件）。一方`page.tsx:1472`の`RouteAxisProfile`描画条件は
  `{selectedCandidate && (<RouteAxisProfile ... />)}`で`hasDetail`を見ていない。
  `handleRouteModeSelect`（page.tsx:800付近）は`if (!layerVisibility.route)
  handleLayerToggle("route", true)`を無条件で実行する。
- Impact: `hasDetail`成立前にチップ操作すると、`layerVisibility.route`が
  ユーザーの意図と無関係にONへ変わるが、地図側の直接的な復帰手段（同じチップの
  再クリック）は`hasDetail`成立までdisabledのまま使えない——チップの状態と
  地図側の操作可能性が一時的に食い違う。
- Root Cause: `RouteAxisProfile`の表示条件を、旧`renderRouteColorSectionBody`の
  ゲート（`hasDetail`）から`selectedCandidate`へ緩めた際、地図チップ側の
  無効化条件（`hasDetail`のまま）との整合を取っていない。
- Recommendation: `RouteAxisProfile`の表示条件を`hasDetail`（旧ゲートと同じ）に
  戻すか、`handleRouteModeSelect`が`hasDetail`成立前は`layerVisibility.route`を
  変更しない（または地図チップのdisabled条件をチップ操作と同期させる）よう揃える。
- Scope: S
- Confidence: High（コードで確認済み。removed-behavior角度Bとcross-file角度Cの
  2エージェントが独立に指摘、直接確認でも再現条件を確認）

### [P2] 削除済みセクション名「生成したルートの色分け」を指す案内文が残っている

- Problem: T518で「生成したルートの色分け」という見出し・独立ブロックは削除され
  「地図の色分け」（RouteAxisProfile内）へ改称・統合されたが、風・勾配の地図表示
  トグルに添える案内文が旧名を指したまま残っている。
- Evidence: `frontend/src/components/RouteSettingsPanel/RouteSettingsPanel.tsx:179`
  付近、`frontend/src/components/Map/mapLayers.ts:547,585`。「ルート確定後は
  『生成したルートの色分け』の『風』で確認できます」に相当する文言（正確な文字列は
  該当行を参照）。`RouteSettingsPanel.test.tsx:379,434`がこの旧文言を`getByTitle`で
  固定しているため、テストは通ったまま文言のドリフトを検知できない。
- Impact: 案内どおりに探しても該当セクションが見つからず、ユーザーが迷子になる。
- Root Cause: セクション名がコード中に文字列として複数箇所へハードコードされており
  （見出し自体の削除時に、それを指す別ファイルの案内文until追従されなかった）、
  1箇所を改称しても他の参照が自動追従しない。
- Recommendation: 案内文を新名称「地図の色分け」へ更新する。恒久対応としては
  セクション名を1箇所の定数として持ち、案内文側はそれを参照する形にする。
- Scope: S
- Confidence: High（文字列はコード上で直接確認可能。removed-behavior角度Bと
  altitude角度の2エージェントが独立に指摘）

### [P2] 内訳の「寄与度の合計＝総合難易度」という表示上の主張が、区間ごとにデータ有無が異なるルートでは成立しない

- Problem: 「総合難易度は…（下の内訳の合計）です」という案内文（RouteAxisProfile.tsx）
  は常に成立するとは限らない。
- Evidence: backendの`overall_difficulty`（`backend/app/domain/difficulty.py:
  composite_difficulty`、`route_generator._with_overall_difficulty`）は**区間ごとに
  その区間で値のある軸だけ**で正規化してから距離加重平均する。一方フロントの
  `RouteAxisProfile.tsx`の`weightSum`はルート全体で1つの値を計算し、`axes`
  （重み>0の軸のうち`axisDifficulties`にキーがあるもの＝ルート全体の距離加重平均値が
  存在する軸）に対して一律に`raw*weight/weightSum`を適用する。区間ごとに評価可能な
  軸が異なるルート（例: 一部区間だけ`surface_q`データが欠落）では、この2つの計算は
  一致しない。
- Impact: 「41/100 総合難易度」という数値と、内訳バーの数値の合計が目に見えてズレる
  ケースがあり得る。欠測区間が多い軸ほど乖離が大きくなる。
- Root Cause: フロント側がbackendの正規化ロジック（区間単位の可変集合での正規化）を
  簡略化し、ルート単位の固定集合で再実装している。
- Recommendation: 短期的には案内文を「近似値」であることが伝わる表現に弱める。
  恒久対応としては、backendが`overall_difficulty`と一緒に軸ごとの寄与度
  （contribution）自体を返し、フロントは受け取った値をそのまま表示する
  （計算ロジックの単一情報源をbackendに保つ）。
- Scope: S（文言調整）／M（backend側で寄与度を返す場合）
- Confidence: Medium（区間ごとのデータ欠落パターンが実際にどれだけ起きるかは
  未検証。correctness角度Aとaltitude角度の2エージェントが独立に指摘）

### [P2] `ComparisonPanel`の軸フィルタを「今」のライブ重みへ変更したことで、比較したい軸自体が表から消えうる

- Problem: 研究モードの実験スロット比較で、スロットごとに異なる重み設定で生成した
  軸のデータがあっても、「今」の`routePreference`で重み0の軸は行ごと表から消える。
- Evidence: `frontend/src/app/page.tsx`（diff該当箇所）の
  `axes={axisCatalog.axes.filter((axis) => (routePreference[axis.axisId] ?? 0) > 0)}`。
  例えば「風0.5」で1回目のスロットを生成した後、風の重みを0にしてから2回目を
  生成すると、両スロットの`topCandidate.axis_difficulties`に風の値が残っていても、
  比較表からは風の行が消える。
- Impact: 複数スロットを横断比較する画面の本来の目的（重み設定を変えて何が
  変わったか見る）と、表示フィルタが逆行する組み合わせがありうる。
- Root Cause: diff自身のコメントは「複数の実験スロットを横断比較する画面のため、
  スロットごとの生成時点の重みではなく『今』の設定基準で揃える」という意図を
  説明しているが、この理由づけと「今0の軸は消す」という結論の向きが逆——横断比較
  だからこそ、どのスロットかに関わらず一度でも評価された軸は残すべき、という
  読み方もできる。
- Recommendation: ユーザーへ「今0の軸も消さず残す」「今のまま消す」のどちらが
  意図と合うか確認する（設計判断の再検討が必要、単純なバグではなく仕様の再考）。
- Scope: S
- Confidence: Medium（設計判断の妥当性についての指摘であり、実装が「間違っている」
  という確度ではない。correctness角度Aのみが指摘）

### [P2] `layerVisibility.route`の意味変更に対するlocalStorage移行が無い

- Problem: 以前「ルート」チップOFF＝色分けレイヤーのみ非表示、だった意味が、
  T518で「候補線・ハロー・矢印・色分けレイヤーすべて非表示」へ広がった。
  この状態は`useStoredState`でlocalStorageへ永続化されている。
- Evidence: `frontend/src/components/Map/MapView.tsx:3153`付近（新設effect）・
  `frontend/src/app/page.tsx:185`付近（`layerVisibility`の既定値定義、
  `route: true`）。既定値はtrueのため新規ユーザーには影響しないが、過去に
  明示的にOFFへ変更して保存したユーザーの既存値はそのまま引き継がれる。
- Impact: 過去に「ルート」をOFFに保存していた利用者は、更新後にルートを生成しても
  地図に候補線が1本も出ない状態から始まる。復帰手段（地図チップ）は`hasDetail`
  成立まで無効化されているため、「候補を生成したのに地図が空に見える」という
  一時的な混乱が起きうる。
- Root Cause: 既存の永続化フラグの意味範囲が広がる変更に対し、移行・救済処理を
  設けていない。
- Recommendation: 実際に影響を受けるユーザー数は限定的と見られる（明示的にOFFへ
  変更した利用者のみ）。対応する場合は、初回読み込み時に「保存値がfalseなら
  一度だけtrueへ戻す」ような1回限りの移行を検討する。優先度は低い。
- Scope: S
- Confidence: Medium（removed-behavior角度Bのみが指摘。影響を受けるユーザーの
  実在は未確認）

### [P2] docs/architecture.mdに、修正済みの「ハローは常時表示」という古い記述が残っている

- Problem: `docs/architecture.md`の該当箇所が「選択中候補のハロー（③）は常時識別
  できるようにする」「常時」と記述しているが、T518でこの層は`routeLayerOn`
  連動へ変更済み。
- Evidence: `docs/architecture.md:164, 166`（該当記述、行番号は変更前基準——今回の
  diffにarchitecture.mdは含まれていないため未反映のまま）。
- Impact: 次に地図レイヤーを触る担当者がこの古い前提のまま実装し、T518が直した
  はずの不整合（「ルートOFFでも線が消えない」）を再導入するリスク。CLAUDE.mdの
  「コミット時の同期ルール」（規模M以上でAPI・ドメイン概念・レイヤー種を新設する
  タスクはarchitecture.md追従を完了条件に含める）の趣旨にも反する
  （このタスクは新規レイヤー種の追加ではなく既存レイヤーの表示条件変更のため、
  同ルールの直接の対象かは微妙——Conventions角度は「非該当」と判定したが、
  記述自体が古いまま残っている実害は変わらない）。
- Root Cause: T518のドキュメント同期は`docs/modules/frontend/*.md`のみ行い、
  `docs/architecture.md`のハロー関連の記述は見落とされた。
- Recommendation: 「常時」を「`routeLayerOn`に連動」へ更新する。
- Scope: S
- Confidence: Medium（cross-file角度Cのみが指摘。architecture.mdの当該記述の
  現在の正確な行番号は未確認のまま）

### [P3] `RouteStyleModeId`の型契約が緩く、対応モードの無いidを渡せてしまう（P2指摘の根本原因）

- Problem: `RouteStyleModeId`は`"difficulty" | (string & {})`——事実上`string`。
  `onRouteStyleModeChange`へ`routeStyleModes`に存在しないidを渡してもコンパイル
  エラーにならない。今回の「非活性チップ」対応（RouteAxisProfile.tsx:188の
  `colorable`チェック）はこの契約の緩さをUI呼び出し側で個別に埋めているに過ぎない。
- Evidence: `frontend/src/components/Map/routeStyleModes.ts`の型定義、および
  `RouteAxisProfile.tsx:188`の`const colorable = routeStyleModes.some((mode) =>
  mode.id === axis.axisId)`。既存の`isRouteStyleModeId(modes, value)`
  （routeStyleModes.ts:301）という同等の判定関数が既にあるにもかかわらず再実装。
- Impact: 将来、軸チップを描画する別コンポーネントが追加された場合、同じ
  `colorable`チェックを個別に再実装する必要がある。忘れれば同じ「無反応チップ」
  バグが再発する。
- Recommendation: `colorableAxisIds`（またはブランド型）を`useAxisCatalog`が
  `routeStyleModes`と一緒に導出し、両方を渡す形にする、または
  `onRouteStyleModeChange`が呼び出し前に自前でガードする共通実装（例:
  `handleRouteModeSelect`内で`isRouteStyleModeId`チェックを行い、無効なidは
  `debugLog`警告のうえ無視する）へ寄せる。
- Scope: M
- Confidence: Medium（altitude角度のみ、設計判断についての指摘）

### [P3] MapView.tsxの表示/非表示ペアが3系統（route候補線・ハロー系・detail-segments）とも手書きで並行実装されている

- Problem: `hideBaseRoutes`・`hideSelectedOutline`（新設）・既存`hideDetailSegments`
  は、いずれも「複数のlayer idを`runWhenStyleReady`でラップして`setLayerVisibility`
  する」という同型の処理を個別に手書きしている。表示側（`drawXxx`内の
  `setLayerVisibility(..., true)`群）も同様に非表示側と別々のリストとして存在する。
- Evidence: `MapView.tsx`の`drawBaseRoutes`/`hideBaseRoutes`（851, 857-859行付近）・
  `drawSelectedOutline`/`hideSelectedOutline`（896-912行付近）。同種の既存機構として
  `setStaticOverlayVisibility`（`MapView.tsx:1845`、T47 R-6でテーブル駆動化済み）が
  既にある。
- Impact: 今回のP1指摘（`redrawAllLayers`の見落とし）と同根——表示側・非表示側・
  呼び出し元（effect×2＋redrawAllLayers）が別々の場所に分散しているため、
  1箇所の更新漏れが起きやすい構造になっている。将来ルート関連レイヤーが1つ
  増えると、表示リスト・非表示リスト・テストの3箇所を個別に直す必要がある。
- Recommendation: P1の推奨対応と同じ——`ROUTE_LAYER_IDS`のような1つの配列と、
  それを一括で表示/非表示にする1つの関数へ集約する。
- Scope: M
- Confidence: High（reuse角度・altitude角度の2エージェントが独立に指摘、実コードで
  該当関数の重複を確認済み）

### [P3] チップUIの再利用不足（CSS重複・凡例ポップオーバー重複・チェックボックス行の3実装目）

- Problem: 以下3点、いずれも「既存の見た目・実装を流用せず、似て非なるものを
  新規に書いた」パターン。
  1. `RouteAxisProfile.module.css`の`.axisToggle`が`RouteSettingsPanel.module.css`の
     `.legendToggle`をプロパティ単位で複製しているが、`@media (max-width:640px)`の
     padding調整（`RouteSettingsPanel.module.css:299-303`）は複製されておらず、
     モバイル幅でチップの余白がルート設定パネルと揃わない（既に発生しているドリフト）。
  2. `RouteAxisProfile.tsx`の凡例Popoverブロック（105-128行付近）が
     `RouteSettingsPanel.tsx`の「重み配分」凡例ポップオーバー（404-432行付近）と
     構造・クラス名までほぼ同一。
  3. 凡例チェックボックス行が、`MapLayersPanel.tsx:171-199`の既存汎用関数
     `renderLegendCheckboxes`の3つ目の独立実装になっている（`entry.isFallback`の
     分岐が今回は落ちている）。
- Evidence: 上記3ファイルの該当行（reuse角度エージェントの詳細出力を参照）。
- Impact: RouteSettingsPanel側の見た目・挙動を変更しても、複製側は追従しない
  （既にモバイル幅のpadding不一致という実害が出ている）。
- Recommendation: CSS Modulesの`composes`（このリポジトリに既存の慣習、
  `frontend/src/components/Map/recipeControls.module.css:12-35`が前例）で
  `.legendToggle`を継承し、状態スタイル（`[aria-pressed="true"]`）だけを
  ローカルで上書きする。凡例ポップオーバー・チェックボックス行は共通コンポーネント
  として切り出す。
- Scope: M
- Confidence: High（reuse角度エージェントが実コードの行番号付きで具体的に指摘）

### [P3] `RouteAxisProfile.tsx`内でチップJSXが3回、色ドットJSXが4回ほぼ同一のまま繰り返されている

- Problem: 「legendChip > 色ドット + ラベル」という構造が、総合難易度行・
  色分け対応軸・色分け非対応軸の3箇所でほぼ丸ごと重複している。
- Evidence: `RouteAxisProfile.tsx`の141-152行（総合難易度）・191-211行
  （軸チップ2分岐）。
- Impact: チップの見た目（例: dotのaria-hidden方針、ラベルのellipsis対応）を
  変えるとき3箇所を直す必要があり、1箇所の更新漏れがドリフトを生む。
- Recommendation: ローカルな`AxisChip({color, label, pressed, onSelect})`
  サブコンポーネントへ抽出する。
- Scope: S
- Confidence: High（simplification角度・reuse角度の2エージェントが独立に指摘）

### [P3] 削除済み機能の残骸（orphaned CSS・orphaned依存パッケージ）

- Problem: `renderRouteColorSectionBody`削除に伴い、以下が使われなくなっている。
  - `frontend/src/components/MapLayersPanel/MapLayersPanel.module.css`の
    `.modeGroup`/`.modeItem`/`.modeItemActive`（193-214行付近）——grep確認済みで
    他に消費者なし。
  - `frontend/src/globals.css:397`付近の、削除済みRadioGroup実装を指す説明コメント。
  - `@radix-ui/react-radio-group`（`frontend/package.json`）——grep確認済みで
    `frontend/src`内に参照ゼロ。
- Evidence: simplification角度エージェントによるgrep結果（詳細は同エージェント
  出力参照）。
- Impact: 実害は軽微（デッドコード）だが、放置するとメンテナンス対象が
  不必要に増え続ける。
- Recommendation: 3点とも削除する（同一コミットで行うのが理想だったが、
  T518は既にpush済みのため別コミットでの後始末となる）。
- Scope: S
- Confidence: High（grepで直接確認可能）

### [P3] `stackBarColorForIndex`の「同じ軸は同じ色」という不変条件が、コメント頼みで複数箇所に分散している

- Problem: `RouteSettingsPanel.tsx`（既存3箇所）と`page.tsx`の新設`axisChipColors`
  （4箇所目）が、それぞれ独立に`stackBarColorForIndex(index, axisCatalog.axes.length)`
  を呼んでいる。「両パネルとも同じ配列・同じ件数を渡す」という前提はコード上の
  コメントで説明されるのみで、型やテストでは強制されていない。
- Evidence: `page.tsx`の`axisChipColors`（useMemo）と`RouteSettingsPanel.tsx:208`の
  対応する呼び出し。
- Impact: どちらかが将来フィルタ済み配列を渡すよう変更されると（`RouteAxisProfile`
  は既にフィルタ済み`axes`を受け取っているため、次の一手として起こりやすい）、
  同じ軸が2つのパネルで異なる色になる。型エラーにもテスト失敗にもならない。
- Recommendation: 色の導出を`useAxisCatalog`側で1回だけ行い、両パネルがその結果
  （axisId→color の Map/Record）を読むだけにする。
- Scope: S
- Confidence: Medium（reuse・simplification・altitudeの3角度が収束して指摘、
  ただし「いつか壊れる」という将来リスクの指摘であり現時点で壊れているわけではない）

### [P3] `routeLayerOn`をeffect依存に追加したことで、チップ切替のたびに無駄なFeatureCollection再構築が起きる

- Problem: 「ルート」チップをON/OFFするたびに、`drawBaseRoutes`/`drawSelectedOutline`
  が`routesToFeatureCollection`でGeoJSONを再構築し、変化していないデータを
  `source.setData()`へ渡し直す。
- Evidence: `MapView.tsx`の該当effect（`[routes, selectedRouteId, routeLayerOn]`
  依存）と`drawBaseRoutes`/`drawSelectedOutline`の実装。
- Impact: 候補数・区間数が多いルートでは、チップの単純なON/OFFのたびに
  MapLibre側のGeoJSON再パース・再タイル化コストが発生する（体感できるほどかは
  ルート規模次第、通常の候補数[8件程度]では軽微と見られる）。
- Recommendation: 可視性の切替と、データ（`setData`）の更新を別のeffectへ分離する
  （可視性専用effectは`[routeLayerOn]`のみに依存し`setLayerVisibility`だけ呼ぶ）。
- Scope: S
- Confidence: Medium（efficiency角度のみ。実際の体感速度への影響は未計測）

### [P3] docs/modules/*.mdへの経緯記述混入（CLAUDE.md/README.mdの明文ルール違反）

- Problem: モジュール設計書（「今のコードがどう動くか」だけを書く場所）に、
  禁止されている経緯説明（「以前は…だったが…した」）が2箇所混入している。
- Evidence:
  1. `docs/modules/frontend/route-settings-and-results.md:143-146`
     「以前は『全体プロファイル』という別タブに独立して存在したが…統合した」
  2. `docs/modules/frontend/page-composition.md:162-163`
     「以前は『全体プロファイル』という別タブだったが、…統合した」（1と
     ほぼ同一内容の重複）
  根拠: `docs/modules/README.md`「記載粒度」節の禁止事項
  「以前は…」「改善計画Txxxで…に変更した」等の経緯説明はdocs/tasks/Txxx.mdの
  役割であり、必要なら`[Txxx](../../tasks/Txxx.md)`と1つリンクを添えるに
  とどめる」。CLAUDE.md「コミット時の同期ルール」がdocs/modules/*.md変更時に
  この節の遵守確認を要求している。
- Impact: モジュール設計書が肥大化し、他の経緯記述禁止違反と同様、将来別の
  変更時にさらに経緯記述が積み重なる呼び水になる（CLAUDE.mdが2026-08-31に
  「サンプリング読みで済ませないこと」を厳命した対象そのもの）。
- Recommendation: 該当2箇所から経緯部分（「以前は…統合した」）を削除し、
  「今の動作」の記述だけを残す（既に括弧の外に「`selectedCandidate`があるときだけ
  `RouteAxisProfile`を同じタブ内に表示する」という現状記述があるため、括弧内を
  削っても仕様記述として成立する）。必要なら`[T518](../../tasks/T518.md)`の
  リンク1つに置き換える。
- Scope: S
- Confidence: High（conventions角度エージェントがルール原文とdiff該当行を
  引用したうえで確認済み）

### [P3] 内訳バーが軸数に応じて理論上100/N%まで潰れ、相対比較という目的が視覚的に成立しにくい

- Problem: バー長を「重み付き寄与度」にしたことで、公開軸8本にほぼ均等な重み
  （各0.125）が配分された標準状態では、raw=100（最悪値）の軸でもバー長は
  トラック幅の約12.5%にしかならない。
- Evidence: `RouteAxisProfile.tsx`の`contribution()`計算とバー描画箇所
  （`style={{ width: ... }}`）。
- Impact: 全行が短いスリバー状になり、「軸間の相対比較」という内訳の目的が
  視覚的に成立しづらい可能性がある。数値列も0-100の難易度ではなく1桁の寄与度
  （例:「6」「3」）になり、同じ画面の「41/100 総合難易度」との読み取り基準の
  違いが説明されないまま残る。
- Recommendation: バーの最大値を「全軸均等配分時の理論上限」ではなく、
  実際に表示中の軸の中での最大値（相対スケール）にする、または寄与度と生の
  難易度の両方を視覚的に区別できる形で見せる、といったUI調整を検討する。
  T518の設計意図（「バー長＝影響度、バー色＝深刻度」）自体は理にかなっているため、
  バグというよりUXチューニングの余地。
- Scope: S〜M（UI再設計を伴う場合）
- Confidence: Medium（correctness角度Aのみの指摘。実際の見やすさは実機での
  主観評価が必要）

### [P3] `RouteCandidate.axis_difficulties`が型上は必須だが実際のスキーマでは任意——欠落時にクラッシュしうる

- Problem: `frontend/src/types/route.ts:40`の`RouteCandidate`型は
  `Omit<Required<Schemas["RouteCandidate"]>, "geometry" | "segments" |
  "score_breakdown">`で`axis_difficulties`を必須扱いにしているが、生成済み
  OpenAPI型（`frontend/src/types/generated/*.ts:1328,1491`）では
  `axis_difficulties?:`と任意になっている。T518以前からある型キャストで、
  今回のdiffが新規に持ち込んだものではない。
- Evidence: 上記2ファイル。`RouteAxisProfile.tsx`の
  `axes.filter((axis) => axisDifficulties[axis.axisId] != null)`は
  `axisDifficulties`自体が`undefined`であるケースを想定していない
  （`undefined[key]`はTypeError）。
  T518以前は「全体プロファイル」タブを開くという明示的な操作をしないと
  この行に到達しなかったが、T518後は`selectedCandidate`が設定された瞬間に
  `RouteAxisProfile`が自動描画されるため、到達条件が広がった。
- Impact: backendが`axis_difficulties`を省略したレスポンスを返すことが
  実際に起きるかは未確認（`RouteCandidate`のdocstラインでは常時計算される
  設計と説明されている）。起きた場合、候補を選択した瞬間にページ全体が
  クラッシュする。
- Root Cause: 型レベルの`Required<>`キャストが、実際のAPIスキーマの
  任意性を握りつぶしている（pre-existing）。
- Recommendation: 実際に省略されうるかbackend側を確認したうえで、
  `RouteAxisProfile`側で`axisDifficulties ?? {}`のような防御を入れるか、
  型キャスト自体を見直す。
- Scope: S
- Confidence: Low〜Medium（cross-file角度Cのみの指摘。pre-existingの型キャストが
  実際に問題を起こす条件[backendが本当にこのフィールドを省略するか]は未検証）

### [P3] `useAxisCatalog()`の別インスタンス間で軸配列が食い違うと、2パネルの色ドットが不一致になりうる

- Problem: `page.tsx`と`RouteSettingsPanel.tsx`は、それぞれ独立に
  `useAxisCatalog()`を呼んでいる（共有ストアではなくコンポーネントごとの
  `useState`）。フェッチタイミング・失敗時のフォールバック
  （`PREFERENCE_AXES`静的リスト）が2箇所で食い違うと、`axisCatalog.axes.length`
  も食い違い、`stackBarColorForIndex(index, length)`の結果が2パネルで
  ズレる。
- Evidence: `frontend/src/hooks/useAxisCatalog.ts`の実装（結果を永続キャッシュ
  しない旨のコメントあり）、`page.tsx`と`RouteSettingsPanel.tsx`双方の
  `useAxisCatalog()`呼び出し。
- Impact: モバイルのBottomSheetでRouteSettingsPanelが再マウントされ、
  その再フェッチだけが失敗（またはpage.tsx側より後にフェッチ完了）する
  ようなタイミング依存の状況で、同じ軸の色ドットが2パネルで異なって
  見える可能性がある。
- Root Cause: 「同じ軸なら同じ色」という不変条件が、共有ストアではなく
  「同じフックを2箇所で呼んでいる」という弱い前提の上に成り立っている。
- Recommendation: 上記の`stackBarColorForIndex`分散指摘（P3参照）と同じ
  対応——色の導出を1箇所（例えばuseAxisCatalog自体の返り値）へ集約する。
- Scope: M
- Confidence: Low（cross-file角度Cのみの指摘。フェッチタイミングのズレが
  実際に発生する頻度は未検証、かなり狭いレースコンディション）

## KEEP（変更しない方がよい設計。理由つき）

- `RouteAxisProfile.tsx`の`contribution()`計算式（`raw*weight/weightSum`、
  backendの`composite_difficulty`と同じ考え方）自体の方向性——「重みの低い軸の
  悪いスコアで、内訳の見た目が過大に見えないようにする」というT518の狙いは、
  ユーザーからの明示的な指摘（「おすすめ度が高いのに重みづけが逆転していると
  混乱する」）に基づく妥当な設計。ズレの指摘（P2）は計算の**精度**についてで
  あり、方向性自体は正しい。
- MapView.tsx側の`drawBaseRoutes`/`drawSelectedOutline`が、既存source更新時にも
  `setLayerVisibility(..., true)`を明示する設計（simplification角度が検証済み、
  「if/elseの両方にvisibility呼び出しを分散させる」のではなく「共有の末尾で
  1回呼ぶ」現在の形が既に最適）。

## REMOVE

- `frontend/src/components/MapLayersPanel/MapLayersPanel.module.css`の
  `.modeGroup`/`.modeItem`/`.modeItemActive`（orphaned、P3参照）
- `@radix-ui/react-radio-group`パッケージ依存（orphaned、P3参照）
- `frontend/src/globals.css:397`付近の、削除済み実装を指す古いコメント

## SIMPLIFY

- `RouteAxisProfile.tsx`の3箇所のチップJSX・4箇所の色ドットJSXを
  `AxisChip`サブコンポーネントへ集約（P3参照）
- `contribution()`（呼び出し元1箇所のみ）は呼び出し側でのインライン計算へ
  戻すことを検討（過剰な抽象化の可能性、simplification角度指摘）

## REFACTOR

- MapView.tsxのルート関連5レイヤー（候補線・ハロー・矢印ハロー・矢印・
  detail-segments）の表示/非表示を、`setStaticOverlayVisibility`と同型の
  テーブル駆動の1機構へ統合する（P1・P3の根本対応）
- `RouteAxisProfile.tsx`と`RouteSettingsPanel.tsx`で重複しているCSS
  （`.axisToggle`/`.legendToggle`）・凡例ポップオーバーJSX・凡例チェックボックス行
  （`MapLayersPanel.tsx`の`renderLegendCheckboxes`）の共通化（P3参照）
- 軸id→色のマッピングを`useAxisCatalog`側へ一元化し、`stackBarColorForIndex`の
  直接呼び出しを複数箇所に分散させない（P3参照）

## EXTEND

- `RouteStyleModeId`の型契約を強化し、`routeStyleModes`に無いidを渡すこと自体を
  コンパイル時に検出できるようにする（P3、根本対応）

## DEFER（必ずトリガー条件を付ける）

- ComparisonPanelの軸フィルタ基準（ライブ重み vs 生成時点の重み）の再設計 ——
  トリガー: ユーザーへ意図を確認し、方針が決まった時点で着手する
- 内訳バーの視覚表現（寄与度の相対スケール化等）の見直し —— トリガー: 実機で
  複数軸のバーを並べて見た際に「短すぎて比較しづらい」という実感がユーザーから
  出た場合

## Regression / Previous Findings

該当なし（RouteAxisProfile.tsx・MapView.tsxのルートレイヤー表示切替は今回のT518が
初めて本格的に手を入れた範囲で、過去のcodereview/codereview-self履歴に同一箇所への
指摘は無い）。

## スコアサマリ

| 指標 | 値 |
|---|---|
| P0件数 / P1件数 / P2件数 / P3件数 | 0 / 2 / 6 / 11 |
| 総合スコア（100点満点） | `100 - (0×20 + 2×10 + 6×3 + 11×1)` = 100 - (0+20+18+11) = 51 |
| 前回同種レビューからの差分 | 該当なし（この範囲への初回codereview） |
| REMOVE/SIMPLIFY/REFACTOR件数 | REMOVE 3 / SIMPLIFY 2 / REFACTOR 3 |
| DEFER件数（トリガー未到達） | 2 |

## Overall Judgment

T518は要求された機能（タブ統合・重み反映・チップ流用・「ルート」チップ修正）を
概ね実現しているが、**まさにその「ルート」チップ修正が目的としていた不変条件
（OFF＝完全非表示）を、スタイル再読み込み経路で再び破っている（P1その1）**ことと、
**タブ統合の結果、軸データが0件の候補では色分け操作自体に到達できなくなる
回帰（P1その2）**という2件のP1は、ユーザーが実際に踏む可能性のある操作
（地図データの再読み込み、データが疎な候補の選択）から発生するため、放置せず
早期に修正することを推奨する。P2群（案内文の残骸・内訳の精度・比較タブの
仕様再考・localStorage移行・ドキュメント同期漏れ）はいずれも実害は限定的だが、
特に案内文の残骸（テストがgetByTitleで固定しているため自動検知できない）は
次の関連改修で見落とされ続けるリスクがある。P3群はコード品質・保守性の指摘が
中心で、緊急対応は不要。
