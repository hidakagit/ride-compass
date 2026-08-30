# 複雑度平衡性レビュー（2026-08-31）

- 実施日: 2026-08-31
- レビュー種別: complexity（単独実施。principles.md 2026-08-31改訂により、complexity/uiは
  対象規模に関わらず常にドメイン分割せず単独で実施する）
- **対象コミット（HEAD固定）: `0958e13`**（`git fetch origin master`実施、ローカルHEAD＝
  origin/master先端で一致を確認済み）。
- **前回complexityレビュー（比較基準）: `.claude/commands/review/history/2026-08-30_all.md`
  Phase 3（対象コミット`a5d5d51`、2026-08-30朝・統合レビュー第9回、正しい設計で単独実施
  された直近の複雑度レビュー）**。同日中にもう1本「統合レビュー第2回」
  （`2026-08-30_all_2.md`、対象`fb40ad8`）が実施されているが、これは誤って
  ドメイン単位（backend/frontend-Map/frontend-その他/docs/ui）へシャーディングした結果
  complexityレンズ固有の出力（規模ウォッチ表・変更コスト表・Keep List照合）が生成されな
  かった回であり、本レビューが「やり直し」の対象そのものである。そのためcomplexity
  固有の比較基準としては採用せず、`a5d5d51`時点のPhase 3を正式な前回値として扱う。
  ただし`2026-08-30_all_2.md`が検出した個別の指摘（P1×3・P2×5・P3×5）はすべて
  T443〜T454として既に起票済みであることを確認し、本レビューでは重複防止のため
  参照のみ行う（該当箇所で明記）。
- 対象範囲: `a5d5d51..0958e13`の58コミット・168ファイル・+9,238/-3,426行。T400系列の
  続き（T414自己是正・T417撤回→T418・T421・T423[T411統合]・T427〜T454起票分・T440
  Part A〜D・T442）が中心。ただし本レビューは**差分を読むのではなくリポジトリ全体を
  横断計測**することが主体のため、上記コミット一覧は範囲の把握にのみ用いた。
- **コードは変更していない（読み取り専用調査）。**

## Executive Summary

T332以降、とりわけT400〜T414〜T423〜T440という一連の「地図×評価軸連動モデル」の設計
反復は、複雑さの配置という観点で見て**改善が後退より明確に上回っている**。具体的には
(1) T432が動的気象レイヤーの適用ロジックを`ensureDynamicWeatherLayer`1関数へ一般化し、
前回レビューが懸念した「bespoke ensure/apply関数の増殖」を実質的に解消済み、(2) T440
Part Dが`ensureWindAxisLayer`/`ensureGradientAxisLayer`等6関数の重複を
`makeEnsureDedicatedWayValueLayer`等3関数へ統合、(3) T411＋T423が「動的材料」（風・
勾配のような、道路自身の状態に依存し既存タイルへ焼き込めない軸）の配信基盤
（`dynamic_way_value_cache.py`・`dynamicWayValues.ts`・`useDynamicWayValues.ts`）を
2件目（勾配）の実装と同時に汎用化し、3件目以降のコストを下げる投資を実際に払った、
(4) T409完了によりdisplay_overrideの後方互換フォールバックが解消、という4点はいずれも
「複雑さを削減する方向の設計反復」であることをコードで確認した。

一方、**ユーザーが特に懸念する「T440のような最小限のゆがんだ修正の積み重ね」に該当する
実例が1件見つかった**: 動的材料の追加パスは「半分だけ」一般化されている。ensure/color/
`dedicated_way_value_layer`判定はT440 Part Dでデータ駆動化されたが、**redraw時の
feature-state再適用・OFF時のクリア・`interactiveLayerIds`所属という3つの責務は
いまだ材料ごとに手書きで複製されたまま**であり、T423（勾配）はこの手書き部分にあった
既知のバグ（風の`redrawAllLayers`未再適用・`interactiveLayerIds`除外漏れ、T425項目3・4）
を「風の実装を見ながら」踏襲する形でそのまま複製したことをT423.md自身が明記している
（詳細はFindings F-2参照）。この種の複製は、風→勾配で1件から2件へ増えており、3件目の
動的材料が来る前に手当てしないと線形に増え続ける構造になっている。

規模ウォッチでは新規の閾値超過は無し（MapView.tsxは引き続き旧閾値2,800行を超過している
が、これはT430〔起票済み・未着手〕の記帳漏れであり中身の複雑さ自体は既に改善済み）。
architecture.mdは今回+7.7%（2,545→2,740行）で3,000行の閾値には未到達だが、
T428〔起票済み〕のもう一方の発火条件「次の規模L以上の設計転換完了時」はT440
（規模L、2026-08-30完了）で既に成立しており、この事実は前回レビューまで気づかれて
いなかった新情報である。P0/P1は今回もゼロ。

## 規模ウォッチ表

実測手順: `backend/app`・`frontend/src`配下の実装ファイル（テスト・生成物・CSS・
migrationを除く）を`wc -l`で全数実測し、上位5件を前回（`a5d5d51`時点の直近complexity
レビュー、2026-08-30_all.md Phase 3。バックエンド上位5件の実数値は同ファイルに
「抜粋」として省略されていたため、直近のフル実測値である`history/2026-08-27_all.md`
Phase 3（対象コミット`f7b8f5e`）の値を基準とした。同期間[`f7b8f5e`→`a5d5d51`]は
Phase 3が「backend上位5件は前回と同一顔ぶれ、いずれも未発火」と明記しているため、
この基準値を`a5d5d51`時点の実質値とみなして差し支えない）と比較する。

### Backend（上位5件、いずれも未発火）

| ファイル | 今回(`0958e13`) | 前回基準(`f7b8f5e`) | 増分 | 発火 |
|---|---|---|---|---|
| `infrastructure/road_graph_repository.py` | 2,652 | 2,432 | +9.0% | 未発火（個別閾値2,800行、T357） |
| `services/road_graph_engine.py` | 874 | 842 | +3.8% | 未発火（個別閾値1,100行、T357） |
| `domain/material_catalog.py` | 815 | 746 | +9.2% | 未発火 |
| `domain/evaluation.py` | 744 | 733 | +1.5% | 未発火 |
| `domain/axis_definitions.py` | 681 | 630 | +8.1% | 未発火 |

新規上位5件入りなし。全件+15%未満、絶対閾値未到達。3回連続（08-23→08-27→08-30→本回）で
backend側は監視外への逸脱が発生していない。

### Frontend（上位5件）

| ファイル | 今回(`0958e13`) | 前回(`a5d5d51`) | 増分 | 発火 |
|---|---|---|---|---|
| `components/Map/MapView.tsx` | 3,114 | 2,992 | +4.1% | ○ 個別閾値2,800行を継続超過（T430起票済み・未着手、下記参照） |
| `app/page.tsx` | 1,827 | 1,726 | +5.9% | 未発火（閾値1,900行） |
| `components/AxisStudio/AxisComposer.tsx` | 1,381 | 1,345 | +2.7% | 未発火（個別閾値1,400行まで残り19行。ただし閾値文言に問題あり、F-1参照） |
| `components/MapOverlayControls/MapOverlayControls.tsx` | 1,139 | 1,490 | **-23.6%** | ▼大幅減少（DEFER解消、後述） |
| `components/Map/mapLayers.ts` | 666 | 636 | +4.7% | 上位5件へ新規登場（分類: 理由つきKEEP、後述） |

`components/Map/icons.tsx`は583行（前回644行、-9.5%）で上位5件から脱落。

### docs/architecture.md

| 今回 | 前回(T286完了時点を初期値とする系列の最新値) | 増分 | 発火 |
|---|---|---|---|
| 2,740行 | 2,545行（`a5d5d51`時点） | +7.7% | 未発火（閾値3,000行）だが、T428のもう一方の発火条件「次の規模L以上の設計転換完了時」はT440（規模L、2026-08-30完了）で成立済み（Regression参照） |

## 変更コスト表

### Case G: 評価軸追加（既存プリミティブ範囲内、breakpoint_linear/categorical/
recipe_then_breakpoint_linearの合成で表現できる軸）

前回（axis_admin API呼び出し1回のみ・コード変更ゼロ）から変化なし。`grep -rn
'axisId === "|axis_id === "'`をfrontend/src全体（テスト除く）に対して実施し、
評価軸の合成・表示判定に関わるハードコード分岐が本番コードに存在しないことを再確認した
（唯一のヒットは`MapLayersPanel.tsx:36`の`axisId === "surface"`だが、これは静的路面
フィルタ軸[roadSurface/roadType切替]の話で評価軸合成とは無関係）。T440 Part Dで
`RouteSettingsPanel.tsx`の`mapColorLayerIdFor`・`mapLayers.ts`の`isAxisStudioLayer`の
最後のハードコード分岐（`axisId === "wind"`等）も撤去済みであることをコードで確認した。

### 新設 Case I: 動的材料（dedicated_way_value_layer、道路自身の向き・状態に依存し
既存の材料タイルへ焼き込めない軸）の追加

T292で消滅したG'/B'/Hを再利用せず新規Caseとして計測する（instructions通り）。
実測はT423（勾配、2件目の実装）の完了コミット`e52f7a1`の`git show --stat`から、
テスト・生成物・docsを除いた実装ファイルのみをカウントした。

| 対象 | ファイル数 | 内訳 |
|---|---|---|
| backend | 9ファイル | 新設4（`domain/gradient.py`・`domain/dynamic_way_values.py`・`services/gradient_way_service.py`・`infrastructure/dynamic_way_value_cache.py`[旧`wind_way_penalty_cache.py`を汎用化]）＋既存拡張5（`api/routers/region.py`・`api/dependencies.py`・`domain/axis_display.py`・`domain/material_catalog.py`・`infrastructure/road_graph_repository.py`） |
| frontend | 15ファイル | 新設4（`gradientAxisLayer.ts`・`gradientGridFill.ts`・`dynamicWayValues.ts`・`useDynamicWayValues.ts`[旧`useWindAxisPenalties.ts`を汎用化]）＋既存拡張11（`page.tsx`・`MapView.tsx`・`mapLayers.ts`・`routeStyleModes.ts`・`windAxisLayer.ts`・`MapOverlayControls.tsx`・`RouteSettingsPanel.tsx`・`WindBearingSlider.tsx`・`useDynamicWeatherLayers.ts`・`regionApi.ts`ほか） |
| 合計 | 約24ファイル | — |

評価: 1件目（風、T414）は汎用基盤が存在しない状態からの実装だったため比較対象データが
無いが、2件目（勾配、T423）は同時にT411（配信機構の汎用化）を実施し、
`dynamic_way_value_cache.py`・`dynamicWayValues.ts`・`useDynamicWayValues.ts`という
共有基盤を作った。この投資により3件目以降の動的材料追加は、上記共有基盤を触らずに
「計算式ファイル1本＋サービス1本＋repository1メソッド＋frontend色分けファイル1〜2本＋
MapView.tsxへの配線」程度（backend3〜4・frontend5〜7、合計10ファイル前後）へ縮む見込み
だが、これは**redraw再適用・feature-stateクリア・interactiveLayerIds所属の3箇所が
依然手書きのままである限り**その分の複製コスト（かつ複製ミスによるバグ混入リスク）が
毎回上乗せされる（F-2参照）。

## Findings

### [P2] F-1. 動的材料（dedicated_way_value_layer）の追加パスが「半分だけ」一般化されており、複製すべきでない責務が材料追加のたびに手書き複製されている

- **Problem**: T440 Part Dは`ensureWindAxisLayer`/`ensureGradientAxisLayer`等の重複を
  `makeEnsureDedicatedWayValueLayer`へ、`RouteSettingsPanel.tsx`/`mapLayers.ts`の
  axis_id文字列分岐を`dedicated_way_value_layer`フラグ駆動へ、それぞれデータ駆動化した
  （Case Iの評価どおり複雑さの削減として正しい設計反復）。しかし**同じMapView.tsx内で
  「redrawAllLayers内での値の再適用」「OFF時のfeature-stateクリア」
  「interactiveLayerIdsへの登録」という3つの責務は一般化されず、材料（wind/gradient）ごとに
  手書きで並置されたまま**であり、この非対称性そのものが、風で見つかった既知のバグを
  勾配へ複製させる原因になっている。
- **Evidence**:
  - `frontend/src/components/Map/MapView.tsx:2241-2327`（`redrawAllLayers`本体）は
    `windAxisPenalties`/`gradientAxisValues`のfeature-state再適用を一切呼んでいない
    （grep実測で`applyAxisFeatureStateValues`の呼び出しは`windAxisPenalties`変更時
    [2947-2948行]・`gradientAxisValues`変更時[2967-2968行]の個別`useEffect`2本のみで、
    `redrawAllLayers`からは呼ばれない。「変わらないデータを更新」ボタン等で
    `redrawAllLayers`のみが呼ばれる経路では両方とも再適用されない）。
  - `docs/tasks/T423.md`「意図的にスコープ外とした点」に「新設した`gradientAxisValues`/
    `gradientFillGeojson`・`GRADIENT_FILL_LAYER_ID`も、風と全く同じbespoke実装パターンを
    踏襲したため、同じ2つのバグ（`redrawAllLayers`内での再適用漏れ・`gradientFill`も
    interactiveLayerIdsから除外されない）を同様に持つ。既存の風の実装との非対称を避ける
    ため意図的にそのまま踏襲した」と明記されている（T423実装者自身の自己申告）。
  - `docs/tasks/T444.md`（起票済み・未着手）は上記のうち`clearRoadTileFeatureState`
    共有によるクリア競合（風・勾配同時ON時に片方OFFで両方消える）を別角度から捕捉している
    （`clearRoadTileFeatureState`が`removeFeatureState({source, sourceLayer})`という
    ソース単位の全消去APIを風・勾配両方のOFF処理から共有していることが根本原因、
    `MapView.tsx:2949-2953,2965-2969`相当）。
- **Impact**: 現状は2材料（風・勾配）に留まっているが、Case Iで確認したとおり3件目以降の
  動的材料追加は今後も起こりうる設計（T411の汎用化そのものが「次の材料が来る」ことを
  前提にしている）。ensure/color/判定は既にデータ駆動化されているため、開発者は
  「新しい材料もこのパターンに従えば安全」と誤認しやすいが、実際には
  redraw再適用・クリア・interactiveLayerIds所属の3箇所は依然「風の実装をコピーして
  material名を書き換える」という手作業が必要であり、T423がまさにその手作業を通じて
  既知のバグ2件を複製した。このまま4件目・5件目の動的材料が追加されると、同型のバグが
  線形に増える。
- **Root Cause**: T440 Part Dの一般化は「axis_idを見て分岐する」形の分岐（判断のロジック）
  の解消に焦点を当てており、「同じ処理を材料ごとに書く」形の単純なコード重複
  （判断を伴わない複製）は対象外だった（T440.md自身が「axis_idのハードコード分岐を
  データ駆動へ直す修正とは性質が異なる」「ここには元々『axis_idを見て判断する』という
  分岐自体が無く、同じ内容の関数が2つ存在するだけの単純なコード重複だった」と明記して
  おり、ensureレイヤー関数についてはこの区別を正しく認識した上で対応している。同じ認識が
  redraw再適用・クリア・interactiveLayerIdsの3箇所には及ばなかった）。
- **Recommendation**: 3件目の動的材料を追加する前に、`makeEnsureDedicatedWayValueLayer`と
  対になる形で「登録済みの全dedicated way valueレイヤーを走査してredrawで再適用する」
  「材料ごとにfeature-stateキーをスコープしてクリアする（ソース単位の全消去をやめる）」
  「interactiveLayerIdsへ自動登録する」の3点を、`dedicated_way_value_layer`フラグを
  持つ軸の一覧（既にmapLayers.tsの`DEDICATED_WAY_VALUE_LAYER_IDS`として存在する）から
  導出する一般化を検討する。**新規チケットの起票は不要**——`T425`（未着手、風の同種
  バグを項目3・4として記載済み）・`T444`（起票済み、クリア競合）のいずれも着手時に
  「勾配にも同じ問題がある」「3件目が来る前に汎用化を検討する」旨のスコープ追記を
  行うことで対応可能。
- **Scope**: S（バグ修正のみ、T425/T444の対応範囲）〜M（3責務の一般化まで含める場合）
- **Confidence**: High（コード実測＋T423.md/T444.mdの一次記録で裏付け）

### [P3] F-2. AxisComposer.tsxの閾値付きKEEP文言「5つ目のshape種到達」がT396/T397後のモデルと不整合

- **Problem**: `context.md`「意図的な設計判断」（Keep List）のAxisComposer.tsxエントリは
  T355（2026-08-27）で「1,400行到達 または 5つ目のshape種到達」という閾値を登録した。
  この文言は当時の`ShapeKind`が4種（`breakpoint_linear`/`recipe_then_breakpoint_linear`/
  `categorical`/`flag_sum`）だった前提で書かれている。T396/T397（2026-08-30、4テンプレート
  →2プリミティブへの再設計）により、現在の`ShapeKind`は3種
  （`breakpoint_linear`/`recipe_then_breakpoint_linear`/`categorical`、`flag_sum`は撤去）
  しかない。
- **Evidence**: `frontend/src/components/AxisStudio/AxisComposer.tsx:33`
  `type ShapeKind = "breakpoint_linear" | "recipe_then_breakpoint_linear" |
  "categorical";`（`SHAPE_KIND_OPTIONS`も3要素、51-69行）。`docs/tasks/T355.md:27`
  「閾値は『1,400行到達 または 5つ目のshape種到達』を提案値とする」（4種時代の記述、
  未更新）。
- **Impact**: 現在の分類だと「5つ目のshape種」は本来「3種→5種で+2種」を意味するはずが、
  文言だけ見ると「4種→5種で+1種」の含意にも読める。実害は無いが、次にこの閾値の発火
  判定をする際（次回complexityレビュー等）に読み手が混乱し、誤判定するおそれがある。
- **Root Cause**: T355登録時点の`ShapeKind`種類数が、その後のT396/T397（設計の単純化）で
  変わったにもかかわらず、Keep Listの閾値文言だけが据え置かれた。
- **Recommendation**: `context.md`のAxisComposer.tsxエントリ（または参照先のT355.md）へ、
  「現在のShapeKindは3種、閾値は『1,400行到達 または 4つ目のshape種到達』」への文言更新を
  提案する。**新規チケットの起票は不要**——次にcontext.mdまたはT355.mdへ触れる機会に
  1行修正すれば足りる規模。
- **Scope**: S / **Confidence**: High

## KEEP

- **T432（動的気象レイヤーの一般化）**: `DYNAMIC_WEATHER_RENDERERS`（7エントリ、raster/
  gridFill/gridMark混在）が単一の`ensureDynamicWeatherLayer`関数で処理されることを実測
  確認した。前回レビューが懸念した「bespoke ensure/apply関数の増加」は、宣言的データ
  （設定オブジェクト）の成長へ転換されており、複雑さの配置として適切（データに複雑さを
  閉じ込め、処理ロジックは1本に保つ）。MapView.tsxの行数増加（2,992→3,114）の多くは
  この種の宣言的成長で、bespoke関数の増殖ではないと確認した。
- **T440 Part D（ensure/color/dedicated_way_value_layer判定のデータ駆動化）**: 6関数
  →3関数への統合、`mapColorLayerIdFor`/`isAxisStudioLayer`のaxis_id文字列比較全廃を
  コードで確認。判断を伴う分岐の一般化としては正しく完了している（F-1で指摘した残課題は
  「判断を伴わない単純複製」であり、性質が異なる）。
- **T411＋T423（動的材料配信基盤の汎用化）**: Case Iで実測したとおり、2件目の実装
  （勾配）と同時に共有基盤（`dynamic_way_value_cache.py`・`dynamicWayValues.ts`・
  `useDynamicWayValues.ts`）を作る投資を払っており、3件目以降のコストを下げる設計判断
  として妥当（「2具体例だけで共通Providerクラスを導入するのは時期尚早」とT423.md自身が
  判断し、計算式は材料ごとの専用実装のまま残した判断も、複雑度平衡の原則
  ［判断原則3「複雑であるべきドメインロジックには適切な複雑さを許容」］に照らして妥当）。
- **T409完了（display_override削除）**: 前回レビューのDEFER（F-6/統合-7）どおり、
  「実際に不要になったことを確認したうえで削除する」という設計原則8の手順を踏んで
  解消された。
- **backend側の規模安定**: road_graph_repository.py/engine.py/material_catalog.py/
  evaluation.py/axis_definitions.pyの上位5件は3回連続（08-27→08-30→本回）で閾値未到達
  のまま推移しており、監視の外側への逸脱が発生していない。
- **Case G（評価軸追加、既存プリミティブ範囲内）**: axis_admin API呼び出し1回・コード
  変更ゼロの状態を維持。ハードコード分岐の再発なし。

## Keep List更新案

（基準ファイル`context.md`自体は書き換えない。以下は提案のみ）

- **維持**: `road_graph_repository.py`（2,800行閾値）・`road_graph_engine.py`
  （1,100行閾値）・`AxisComposer.tsx`（1,400行閾値、ただし「5つ目のshape種」の文言は
  F-2のとおり更新提案）。
- **更新提案（T430の実施内容そのもの、新規ではなく既存起票の後押し）**: `MapView.tsx`の
  Keep List閾値を2,800行→3,200行へ引き上げ、種類数条件を
  「gridFill/gridMark等の描画ロジックを持つレンダラーの件数」（現在1件:
  `windVector`のみ）へ再定義する。**根拠が今回さらに強まった**——T432により
  raster専用エントリが実際にノーカウント相当の扱い（単一適用関数）になったことを
  コードで確認できたため、この更新は「将来の予防」ではなく「既に起きた改善の追認」
  である。
- **クローズ提案（新規）**: `MapOverlayControls.tsx`の閾値登録DEFER（前回F-4/統合-5、
  「T418完了まで意図的に見送る」）は、トリガー（T418完了）が成立した結果、
  登録が不要になった形で解消したと提案する。T418（評価軸チップの地図UI撤去）により
  ファイル自体が1,490→1,139行（-23.6%）へ縮小し、成長トレンド自体が反転したため。
  次に閾値監視が必要になるのは新たな急成長が観測された時点でよい。
- **新規登場の扱い**: `mapLayers.ts`（636→666行、+4.7%、上位5件へ新規登場）は
  理由つきKEEPとする。増分の主因はT423（勾配の`DEDICATED_WAY_VALUE_LAYER_IDS`等の
  カタログ登録）で、既存の`RAMP_AXES`/`AXIS_LABELS`と同じ「ビルド時静的生成物からの
  片側import」パターンに沿った宣言的成長であり、bespoke分岐の増加ではない
  （T440.md自身が「ライブなaxis-catalogをここへ動的に注入する設計は見送り、既存パターン
  に揃えた」と明記）。閾値登録は不要、監視のみ継続。

## REMOVE / SIMPLIFY

該当なし。

## REFACTOR

F-1（動的材料のredraw再適用・クリア・interactiveLayerIds所属の一般化）。ただし
Scope: S〜Mかつ既存T425/T444のスコープ内で対応可能なため、独立REFACTORタスクとしての
起票は不要と判断する。

## EXTEND

該当なし。

## DEFER

- F-1の一般化（3責務のヘルパー抽出）そのものは、2材料時点では実害（バグ2件）を
  T425/T444で個別修正すれば足りるため、トリガー「3件目の動的材料を追加する判断をした
  時点」までDEFERしてよい。個別バグ修正（T425/T444）自体はDEFER対象外（既に起票済み・
  着手可能）。
- 既存のT411/T409相当のDEFERは対象期間中に解消済み（Regression参照）。新規のDEFERは
  上記1件のみ。

## Regression / Previous Findings

前回complexityレビュー（`2026-08-30_all.md` Phase 3、対象`a5d5d51`）のF-1〜F-6との対応:

- **F-1（MapView.tsx閾値二重超過、次閾値未設定）→ 継続（T430起票済み・未着手）**。
  行数はさらに増加（2,992→3,114）。ただし今回の実測で分かったとおり、F-1が問題視した
  「bespoke ensure/apply関数の増加」自体はT432（動的気象レイヤー一般化）で実質的に
  解消済みであり、T430が未着手のまま残っているのは**閾値の記帳（Keep Listの数値更新）
  のみ**である。T430を着手する際は、種類数条件の再定義がT432によって既に正しい形
  （raster専用ノーカウント相当）になっていることをそのまま確認・記録すればよく、
  追加のコード調査は不要と見込まれる。
- **F-2（architecture.md 3度目の再肥大化＋§735/経緯節の内部矛盾）→ 対応中
  （T427・T428ともに起票済み・未着手）**。行数は2,545→2,740（+7.7%）でさらに増加、
  3,000行の閾値には未到達。**新情報**: T428が定めたもう一方の発火条件「次の規模L以上の
  設計転換完了時」は、T440（規模L、2026-08-30完了）によって既に成立している。前回
  レビュー時点（T440着手前）ではこの条件はまだ発火していなかったため、この事実は今回
  初めて確認されたものである。T428は依存タスクT427（記述整合）を先に済ませる方針だが、
  T427も未着手のまま。優先度を「次の閑散期」から一段引き上げることを推奨する。
- **F-3（AxisComposer.tsx 2回連続+15%成長、個別閾値未到達）→ 沈静化**。今回の増分は
  +2.7%（1,345→1,381行）で、T355登録時に懸念された急成長トレンドは収まった。個別閾値
  1,400行まで残り19行、僅差だが監視継続で足りる。ただし閾値文言自体の問題を新規
  F-2として指摘した（上記）。
- **F-4（MapOverlayControls.tsx +30.6%成長、T418完了までDEFER）→ 解消（トリガー成立、
  ただし成長ではなく縮小という形で）**。T418完了（2026-08-30、コミット`0ee439b`）により
  評価軸チップが地図UIから撤去され、ファイル自体が1,490→1,139行（-23.6%）へ縮小した。
  Keep List更新案のとおりクローズを提案する。
- **F-5（icons.tsx +29.6%成長、上位5件へ新規登場）→ 解消**。583行（-9.5%）へ減少し
  上位5件から脱落した。
- **F-6（display_overrideの後方互換フォールバック、T409着手判断待ち）→ 解消**。
  T409完了（2026-08-30）によりコード側フィールド・DBカラム（dev環境）が削除された。
  なお`docs/tasks/T409.md`「実装内容」節の余談として、削除前のスナップショット比較で
  display_overrideとは無関係な5軸分の内容差分（T406〜T414系のAPI経由編集が
  `dump_axis_definitions_snapshot.py`の手動再実行漏れで蓄積したもの）が見つかった
  という記録があるが、これは後続のT442（完了、`git diff`クリーンで裏取り済み）で
  fresh bootstrap相当の差分が解消されたことを確認済みであり、追加対応は不要。

`2026-08-30_all_2.md`（誤ったシャーディングで実施された回、対象`fb40ad8`）が検出した
P1×3・P2×5・P3×5はすべてT443〜T454として既に起票済みであることを確認した。本レビュー
（複雑度レンズに固有の横断計測）の観点から追加できた新情報は上記F-2（architecture.md
のT428トリガー成立）のみで、他はいずれも重複が無いことを確認したのみで新規指摘化していない。

## スコアサマリ

Findingsの件数から機械的に算出する。

| 指標 | 値 |
|---|---|
| P0件数 / P1件数 / P2件数 / P3件数 | 0 / 0 / 1 / 1 |
| 総合スコア（100点満点） | `100 - (0×20 + 0×10 + 1×3 + 1×1)` = **96** |
| 前回同種レビューからの差分 | +6（前回`2026-08-30_all.md` Phase 3: 90点、P2×2+P3×4） |
| REMOVE/SIMPLIFY/REFACTOR件数 | 0 / 0 / 1（F-1、ただし独立起票不要） |
| DEFER件数（トリガー未到達） | 1（F-1の3責務一般化、「3件目の動的材料追加判断時」がトリガー） |

## Overall Judgment

T332以降、特にT400〜T414〜T423〜T440という一連の設計反復は、複雑さの配置という観点で
一貫して改善方向にある。T432（動的気象レイヤーの一般化）・T440 Part D（ensure/color/
判定のデータ駆動化）・T411+T423（動的材料配信基盤の汎用化）はいずれも「判断を伴う
分岐の一般化」を正しく実施しており、前回レビューが懸念した規模ウォッチの発火要因
（MapView.tsxのbespoke関数増殖）は実質的に解消済みで、残る作業はT430という既存起票の
記帳のみである。backend側は3回連続で規模ウォッチの逸脱なし、評価軸追加（Case G）は
コード変更ゼロを維持している。

ユーザーが懸念する「T440のような最小限のゆがんだ修正の積み重ね」については、T440
自体はむしろ良い方向の一般化だったが、**その一般化が「判断を伴う分岐」にしか及ばず
「判断を伴わない単純な複製」（redraw再適用・feature-stateクリア・
interactiveLayerIds所属）には及んでいない**という非対称性が実際に見つかった（F-1）。
T423（勾配）はこの隙間にあった風の既知バグ2件をそのまま複製しており、これは
まさにユーザーが懸念する「積み重ねで負債が増える」パターンの実例である。ただし
実害は2材料に留まっており、既存のT425/T444のスコープ内で対応可能な規模（S〜M）に
とどまる——3件目の動的材料が来る前に対応すれば、これ以上の複製は防げる。

architecture.mdの記録鮮度管理は3回目の停滞が続いているが、今回T428のDEFER条件
（規模L設計転換完了）がT440によって成立したことが新たに判明した。前回まで
「次の閑散期に検討」という低い優先度だったものが、条件成立により実質的に
「着手可能」へ変わっている点は、T427・T428の着手判断において考慮に値する。

総合スコア96点（P2×1・P3×1のみ）は前回90点から改善しており、複雑さの配置という
観点で見た本期間の設計品質は高水準を維持している。
