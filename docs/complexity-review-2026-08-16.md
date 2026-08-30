# 複雑度平衡レビュー（2026-08-16・第4回）

[complexity-review-2026-08-15.md](complexity-review-2026-08-15.md)（第2回・複雑度平衡）・
[research-interface-review-2026-08-15.md](research-interface-review-2026-08-15.md)（第3回・研究IF）に続く
全体レビューの記録。実行計画は [improvement-plan.md](improvement-plan.md) の「第4回レビュー対応」節（T43〜T47）を参照。
詳細版レポート（健全性採点の根拠・認知負荷トレース・推奨アーキテクチャの全文）は
Artifact <https://claude.ai/code/artifact/48dfa30c-38fa-4480-9f99-cc495b7e960c> に公開済み。

レビュー方法: backend app配下 全45モジュール・migrations 0001〜0005・batch・scripts、
frontend src配下の全コンポーネント/hooks/lib/services/types・設定類を**全ファイル通読**し、
docsの完了記録（T17/T18/T21/T23〜T40/P0/P1）を実コード・コミット実績（直近40コミット）と突き合わせた。

---

## 総合評価

**前回（第2回）レビューの宿題は実コード上でも完済されており、大規模変更3日目のコードベースとして
引き続き異例に健全。** 過剰最適化・理由なき抽象化・理由なきデータ変換は今回もゼロ。
architecture.mdと実装の乖離も検出されなかった。残る構造税は
**「評価軸を1つ増やすたびに同じ4軸合成リストを3ファイルで編集する重複」（R-1）**と
**「撤去期限が2026-08-29に到来するOverpassフォールバックの2×2構成」（R-2）**の2点に収斂した。
全面リファクタリングは不要。静的道路属性P2（評価軸が2つ増える）の**着手前に半日分の小粒統合
（T43〜T46）**を済ませることだけを推奨する。

5段階評価: Architecture 4 / Complexity Balance 4（前回3） / Responsibility Separation 4 /
Data Model 4（前回3） / Data Flow 4 / Extensibility 4 / Maintainability 4 / Performance 5 /
Testability 5 / FE-BE Boundary 5

---

## 前回（第2回）指摘の解消状況（実コードで確認）

| 前回 | 状態 | 確認内容 |
|---|---|---|
| I-1 二重評価パイプライン | ✅解消（T21） | 語彙（classify_osm_surface）・集約（distance_weighted_*）・重み（route_preference.yaml）が両エンジン完全共通。ORS数値ID語彙・extras依存は撤去済み。意図的に残る差はwindの時間展開のみ（engineフィールドで識別） |
| I-2 属性追加経路の広さ | ✅短縮を実証 | P0（表示のみ3属性）が「ALLOWED_WAY_TAGS＋MVT SQL＋世代ペア＋フロントカタログ」の5〜6箇所で完了。tags jsonbにより列追加・migration不要 |
| I-3 マイグレーション不在 | ✅解消（T17） | migrations 0002〜0005で4回実証。create_tablesは凍結維持 |
| I-4 フォールバック2×2 | ⏳条件待ち | 撤去条件の前半（関東取込完了）が2026-08-15成立。「新属性をフォールバック側に実装しない」はP0/P1で遵守を確認 → R-2 |
| I-5 ファサード委譲 | ✅契約として定着 | P1の新属性メソッド3本が「個別リポジトリ実装＋対称委譲」の規約どおり追加された |
| I-6 surface_attributes重複 | ✅解消（T9） | JOIN導出化・DROP TABLE済み |
| I-7 ORS固有形式の漏出 | ✅解消（T21） | surface_summary/surface_values・extrasパース・数値ID語彙すべて削除済み |
| I-8 手動同期ペア2組 | ✅解消（T19） | region-tile-config.json照合テストがCIで機能。ただし新たな同期ペアが2組発生 → R-3/R-7 |
| I-9 本番構成の1表明示 | ✅解消（T20） | .env.exampleに3プロファイル表あり。DBなし時の評価縮退のみ未記載 → R-9 |
| I-10 全量ロードのスケール壁 | ✅DEFER維持 | 先回り実装なし（正しい） |

---

## Top Issues（R-1〜R-10、全体最適への影響順）

### R-1. 区間評価の4軸合成が3ファイルに重複〔最重要・P2の前に〕→ T43

「gradient/wind/road/stopの難易度を計算し、(難易度, preference重み)のリストで
`composite_difficulty`へ渡す」同一ブロックが
`openrouteservice_engine._build_segment_details`・`road_graph_engine._build_segment_details`・
`domain/evaluation.compute_edge_cost` の3箇所に存在する。P1（停止密度）のコミットで実際に
3箇所すべてへ同じ4行が追加された実績があり、P2（交通ストレス・交差点密度）でも軸ごとに繰り返される。

- **根本原因**: T21で語彙・集約・重みは一本化されたが、「生値セット→難易度セット→合成」の
  組み立てだけがエンジン/評価器の手元に残った
- **推奨**: `domain/difficulty.py`へ純関数を1つ追加し3箇所を置換（挙動不変）。
  軸追加時の編集箇所が3→1になる。RouteSegmentDetail構築（データ源がエンジン固有）は残す

### R-2. Overpassフォールバック撤去（T22）の期限到来 → T22へ手順追記

撤去条件の前半（関東圏PBF取込完了）が2026-08-15に成立し、**最短2026-08-29に撤去可能**。
「発動ログ0件2週間」を確認する具体的手順が未文書化だったため、T22へ追記した（本番ログでの
検索対象: 「取込範囲外」WARNINGと`region:overpass`/`graph:overpass`カテゴリ）。
撤去でGraphService/RegionServiceの分岐・`vector_tile.py`全体・`OverpassClient.get_roads`・
2×2構成マトリクスが消える。それまで新属性をフォールバック側に実装しない原則は維持。

### R-3. 空間マッチ半径15m/30mの二重定義 → T44

`openrouteservice_engine.py`の定数（SURFACE 30m・STOP_POI 15m）と
`AttributeRepository`各メソッドのデフォルト引数が「コメントで揃える」手動同期になっている。
road_graphエンジン側はデフォルト引数を暗黙使用しており、片側だけ変えると両エンジンの評価が
静かに食い違う。設計原則5（検知テストなしの手動同期ペア新設禁止）に抵触。domain定数へ集約する。

### R-4. ComparisonPanelがT25カタログ化から漏れ、stop軸が記録されない → T45

`formatWeights`がpref側を標高/路面/風の3軸だけ列挙し`stop_weight`が出ない。METRIC_ROWSにも
stop_density行が無い。研究モードで`stop_weight`を変えた実験を比較すると条件表示に差が現れず、
実験記録の完全性（研究IFの根幹）を損なう。evaluationAxesカタログからの列挙生成へ置換する。

### R-5. stop_densityがおすすめ度（total_score）に効かない非対称 → T47（判断の明文化のみ）

scoring.yamlは距離/標高/風/路面の4軸のまま、preference側にはstopがある。P1のスコープ判断としては
妥当だが、放置するとP2でも「評価には入れたが推薦には入れ忘れた」が既成事実化しやすい。
今は変更せず、P2タスク定義に「scoring軸へ追加するか」の明示判断を含める。

### R-6. page.tsx（799行）・MapView.tsx（1,009行）の成長 → T47（閾値の記録のみ、T91・T123で再設定）

前回KEEP判断時（492行／751行）から+62%／+34%。増分は正当な機能追加（モバイル対応・研究IF）で、
宣言的カタログのおかげで可読性はまだ保たれている。**今回は分割しない**。当初の閾値
「静的レイヤーをあと2種類追加する時点」または「MapView 1,200行到達」は統合レビュー
（2026-08-16）時点で両条件成立・約束の2点（(a)静的レイヤーのensure/setペアの宣言的ループ化、
(b)page.tsxの保存付き状態のuseStoredState抽出）ともT47で消化済み。その後も静的レイヤー追加
（T54の停止要因POI等）でMapView.tsxが増加し続けたため、T91（2026-08-17）で新しい閾値
「MapView.tsx 1,800行到達」または「STATIC_OVERLAY_LAYERS 10種到達」を再設定した。

複雑度平衡性レビュー（2026-08-18）F-1（1,908行で1,800行閾値が発火）＋F-2（3つ目のレシピ軸
追加コスト約2,150行・64ファイル）を受け、T123（2026-08-18完了）でMapView.tsxの内訳ポップアップ
双子（`recipeBreakdownPopup.ts`）・レイヤーデータ状態（`useLayerDataStatus.ts`）を専用モジュールへ
抽出し1,654行へ縮小（`trafficStressExpression.ts`/`safetyExpression.ts`の補正ブロック生成も
`recipeExpression.ts`へ共有化、`region_service.py`/`region.py`/`regionApi.ts`の双子も畳んだ）。
新しい閾値（レビューF-1提案）: **「MapView.tsx 2,000行到達」または「STATIC_OVERLAY_LAYERS 10種
到達」または「3つ目のレシピ軸をMapView内へミラー追加しようとした時点」**
（2026-08-18時点: 1,654行・7種）。到達時は改めて対応（分割要否を含む）を判断する。

**2026-08-18（T130, N1/N2レシピ分離）再検討**: T124直後に「道路適正」
（`roadSuitabilityRecipe`）・「自動車密度」（`motorVehicleDensityRecipe`）という3本目・4本目の
レシピ軸をMapView.tsxへミラー追加した（`setStaticOverlayFilters`のパラメータ・複数の
`useEffect`依存配列・`redrawPropsRef`・ポップアップ評価ブロックの4箇所へ、既存の
`trafficStressRecipe`/`safetyRecipe`と同じパターンで追記）。上記閾値のうち「3つ目のレシピ軸を
MapView内へミラー追加しようとした時点」は行数・レイヤー数とは独立した条件のため、他の2条件が
未到達でも判断が必要と判断し、この場で実施した。
- 実測: MapView.tsx 1,804行（閾値2,000行に対し196行の余裕）・STATIC_OVERLAY_LAYERS 8種
  （閾値10種に対し余裕あり）。
- 判断: **KEEP（分割しない）**。ミラー箇所は既存4箇所（props・useEffect依存配列・
  redrawPropsRef・ポップアップ評価）のパターンが3本目・4本目でも機械的に踏襲できており、
  軸追加のたびに新しい配線経路が生まれる兆候はない。むしろ本レビュー（ultrareview）指摘で
  `carClosenessExpr()`が`setStaticOverlayFilters`・ポップアップ評価の双方で軸ごとに二重計算
  されていた無駄を発見し、事前計算結果を共有する形（`buildTrafficStressExpression`/
  `buildSafetyExpression`の追加引数）へ修正済み——ミラー箇所が増えても「軸間で共有すべき
  計算を1箇所にまとめる」という既存原則（`setStaticOverlayFilters`冒頭のコメント）を
  拡張するだけで対応でき、構造的な分割は不要と判断した。
- 新しい閾値: 「MapView.tsx 2,000行到達」または「STATIC_OVERLAY_LAYERS 10種到達」または
  **「5つ目のレシピ軸をMapView内へミラー追加しようとした時点」**（3本目→5本目へ繰り上げ。
  今回2本まとめて追加し「3本目」条件を消化したため）。

**2026-08-19（T145b、レジストリ駆動のramp軸自動生成）以降の閾値再定義**: T145bが
「事実はタイルに、解釈はクライアントに」方針を導入し、`STATIC_OVERLAY_LAYERS`は手書き
エントリ＋`RAMP_AXES`（レジストリのkind="ramp"軸から`makeEnsureAxisRampLayer`で自動生成、
現状stop_density・accidentの2種）の合成になった。ramp軸はレジストリ登録＋タイル焼き込み
だけでMapView.tsx側の追記が実測ゼロのまま増える構造のため、「STATIC_OVERLAY_LAYERS 10種
到達」という閾値が測ろうとしていたリスク（軸追加のたびにMapView.tsxへ手書きコストが
増える）を、ramp軸の増加はもはや捕捉しない。統合レビュー2026-08-19（complexity F-1）で
種類数条件が「10種」に到達したことが判明したが、内訳は手書き7件（T148の安全度削除で
8→7）＋ramp2件＝9件であり、閾値の前提（1軸=1手書きミラー）自体が既に崩れていたと判断し、
改善計画T157でカウント方式を以下へ再定義する（コード変更なし、基準整備のみ）。
- 新しい閾値: **「手書きSTATIC_OVERLAY_LAYERS（ramp軸を除く）10件到達」**または
  **「bespoke種の軸（現状car_stress・night、タグの複雑な組み合わせが必要でramp化できない軸）
  が3件目に増加」**または「MapView.tsx 2,000行到達」または「5つ目のレシピ軸をMapView内へ
  ミラー追加しようとした時点」（既存2条件は維持）。
- 実測（2026-08-19時点）: MapView.tsx 1,766行（閾値2,000行に対し234行の余裕）・
  手書きSTATIC_OVERLAY_LAYERS 7件（閾値10件に対し余裕あり、T148の安全度削除で8→7）・
  bespoke種2件（car_stress・night、閾値3件目に対し余裕あり）。
- ramp種の軸自体が増える分には、この閾値は意図的にノーカウントとする（MapView.tsx側の
  実コストがO(1)のため）。次に手書きレイヤー・bespoke種の軸が増えるタイミングで
  この閾値を再確認する。

**2026-08-22（T184、動的気象レイヤーの共通契約導入）以降の閾値再定義**: 統合レビュー
2026-08-22（改訂-6、旧統合-5）で、MapView.tsxが2,502行（閾値2,000行に対し502行の超過で
発火）・page.tsxが1,615行（閾値1,300行に対し315行の超過で発火。ただしuseState+
useStoredState数は13件で40件の閾値には遠く未到達）と判明した。精査の結果、両ファイルの
増分は既存閾値が捕捉しようとしていたリスク（軸追加のたびの手書きコスト増）とは異なる、
T184が正しく設計した新しい成長軸（動的気象レイヤーの描画スペック登録・時刻タイムライン
統合ロジック）によるものであり、以下のように判断・対応した。

- **MapView.tsx**: 増分の主因は`DYNAMIC_WEATHER_RENDERERS`（レンダラー仕様の宣言的
  レジストリ、現在2件: precipitationNowcast/windVector）と、風の矢印アイコンのCanvas 2D
  描画（`createWindArrowIcon`等、約100行）。T184の共通契約は「描画スペック
  （DYNAMIC_WEATHER_RENDERERS）はMapView.tsxに集約する」ことを設計として定めており、
  この部分はSTATIC_OVERLAY_LAYERSと同種の「宣言だけ増える」構造のため分割対象ではない。
  一方、Canvas描画（`cubicBezierPoint`/`fillTaperedRibbon`/`createWindArrowIcon`）は
  MapLibre/DOM以外に依存しない純粋な幾何計算であり、契約の対象外と判断し
  `windArrowIcon.ts`（新設、約110行）へ抽出した（改善計画T201、windArrowIcon.test.tsで
  最小限のスモークテストを追加）。抽出後の実測は2,401行（閾値2,000行に対し依然401行の
  超過）。新しい閾値は「種類数条件」を`DYNAMIC_WEATHER_RENDERERS`向けに追加し、
  行数閾値も実態に合わせて引き上げる: **「MapView.tsx 2,800行到達」または
  「手書きSTATIC_OVERLAY_LAYERS（ramp軸除く）10件到達」または「bespoke種の軸3件目」または
  「5つ目のレシピ軸をMapView内へミラー追加しようとした時点」または
  「DYNAMIC_WEATHER_RENDERERSのスペックが5件目に増加した時点」**（既存4条件は維持、
  最後の1条件を新設）。
- **page.tsx**: 増分の主因は動的気象レイヤーの時刻タイムライン統合（`mergeFrameTimes`・
  `frameIndexForTime`・`dynamicWeather`単一propの組み立て）で、フェッチ・穴あき対策の
  ロジック自体は既に`hooks/useWeatherGrid.ts`へ抽出済み（-115行の実績）。state数13件は
  40件の閾値に対し十分な余裕があり、「stateの無秩序な蓄積」という当初のリスクは顕在化して
  いない（orchestrationのグルーコードが増えているだけ）。閾値を実態に合わせ引き上げる:
  **「page.tsx 1,900行到達」または「useState+useStoredState合計40件到達」**（後者は維持）。
- 実測（2026-08-22時点）: MapView.tsx 2,401行（新閾値2,800行に対し399行の余裕）・
  DYNAMIC_WEATHER_RENDERERS 2件（閾値5件に対し余裕あり）・page.tsx 1,615行
  （新閾値1,900行に対し285行の余裕）・state 13件（閾値40件に対し余裕あり）。

### R-7. BICYCLE_INFRA_LABELSの語彙複製 → T46

`MapView.tsx`のポップアップ用ラベル辞書（6件）が`staticAttributeLayers.ts`の
BICYCLE_INFRA_CATEGORIESと完全一致の写し（検知テストなし）。カタログから導出する。
SMOOTHNESS_LABELSは唯一の定義のため現状維持でよい。

### R-8. Repositoryファサード委譲17メソッド（P1で+3）

**何もしない。** T18で確定した正式契約であり、P1も規約どおり運用された。30本超で再検討。

### R-9. DBなしプロファイルの機能縮退が未明文化 → T47

T21以降、`road_graph_use_repository=false`ではORSエンジンでも路面・停止評価が全区間Noneになる。
.env.exampleのプロファイル表へ1行追記する（コード変更なし）。

### R-10. 未コミットのdev用batスクリプト → T47

`restart-dev.bat`/`stop-dev.bat`がuntrackedのまま。コミットして用途を1行書くか削除するかを決める。

---

## Keep List（変更しない方がよい設計。前回Keep Listを全面再確認のうえ更新）

- **エンジン切替そのもの**（評価一本化後は「経路をどう引くか」だけの差になった。併存維持が正しい）
- **LoopRoutingEngineの3段階ポート契約**（trace→距離フィルタ→evaluate）
- **生OSM層/派生グラフの分離・split_at鮮度判定・決定論的ID採番**
- **`get_or_build_graph_with_attributes`の3経路**（全分岐に実測根拠）
- **正準語彙のSQLバインド＋生成物照合**（traffic_stress基本値の配列バインドはこの型の正しい拡張）
- **scoring.yaml（相対）/route_preference.yaml（絶対）の分離**と、ComparisonPanelが
  total_scoreを実験間比較に出さない設計
- **Repositoryファサードのフラット委譲契約**（対称追加の規約ごと）
- **PBF取込バッチのasyncpg COPY直行**（Repository迂回はランタイムと意味論が揃う限り正当。
  osm_adapter共有がその担保）
- **フロントの宣言的カタログ5系統**（mapLayers / roadFilterAxes / routeStyleModes /
  staticAttributeLayers / evaluationAxes）
- **BottomSheet×2とrender関数共有**（デスクトップ/モバイルの中身重複回避の現実解）
- **意図的不整合の管理方式**（windの時間展開差＝engineフィールドで識別）
- **実測駆動の最適化すべて**（ST_AsMVT・KNNのWHERE外出し・GiST遅延構築・COPYバルク・
  to_thread・change_detection付きUPSERT。premature optimizationは今回もゼロ）
- **`/api/routes/preview`の残置・MAX_CONCURRENT系の非共通化**
- **ログ・観測基盤**（request_id全レコード注入・抑制付きWARNING・/api/debug/stats）
- **page.tsx / MapView.tsx の現状維持**（MapView.tsxはR-6の閾値〔2,800行 or 手書き
  STATIC_OVERLAY_LAYERS（ramp軸除く）10件 or bespoke種の軸3件目 or 5つ目のレシピ軸の
  MapView内ミラー追加 or DYNAMIC_WEATHER_RENDERERSのスペック5件目、T201（2026-08-22）で
  T184の動的気象レイヤー共通契約導入に合わせ再定義〕、page.tsxは独立した閾値
  〔useState+useStoredState合計40件 or 1,900行、T201（2026-08-22）で再定義〕、
  それぞれ到達までは分割しない）

---

## 変更コストシミュレーション（要約・実績ベース）

| Case | 変更 | 容易度 | 根拠 |
|---|---|---|---|
| A | 道路属性追加（表示のみ） | 易〜中 | P0で3属性実証。5〜6箇所・migration不要（前回予測を達成） |
| B | 評価ロジック変更 | 易 | difficulty.py/compute_edge_cost/YAMLに局所化 |
| C | ルーティングエンジン変更 | 易 | ポート3メソッド＋DI分岐＋config。評価一本化で新エンジンは評価コード不要（前回より改善） |
| D | PostGIS構造変更 | 中 | migration機構が4回実証。関東全域再取込777秒の実績 |
| E | 地図表示変更 | 易〜中 | カタログ編集のみ。新規レイヤーはMapView本体約40行（R-6の閾値で解消予定） |
| F | 外部API変更 | 易 | クライアント1ファイル＋DI。ORS固有漏出はT21で解消（前回「中」→「易」） |
| G | 新しい評価指標追加 | 中 | P1実測: 新データ源込みでbackend実装18ファイル。way由来なら10〜12箇所。T43で3箇所重複→1箇所（前回「難」→「中」） |
| G' | レシピ付き評価軸追加 | 中〜難 | T119実測（安全度軸新設）: 64ファイル・+3,677/-394行。参考値へ性質変更（次回、真に新規の単軸追加時に再検証） |
| G'' | 軸の共通材料の外出し・再構成 | 中〜難 | T130実測（道路適正・自動車密度の2軸を同時追加、既存の交通ストレス・安全度の共通材料を`domain/recipe.py`へ外出し）: 70ファイル・+3,938/-2,084行。G'（真っさらな新規軸追加）とは性質が異なるため区別する |

---

## 実施順序（Phase）

1. **Phase 1（今すぐ・半日）**: T43〜T46＋T47。すべて「軸・属性追加時の編集箇所」を減らす作業で、
   P2の前に済ませるとコスト削減が2回以上回収される。全項目挙動不変・既存テストが安全網
2. **Phase 2（2026-08-29以降・条件成立確認後）**: T22フォールバック一括撤去
3. **Phase 3（次の機能開発と同時）**: 静的道路属性P2（trafficStress・交差点密度の評価組み込み）を
   Phase 1で軽くなった1本道で実施。scoring軸追加の可否をタスク定義内で明示判断（R-5）
4. **Phase 4（トリガー待ち・着手しない）**: T10（DEM化）・T11（segmentsビン化）・T12（スケールADR）・
   フロント分割（R-6閾値到達時）。トリガー未到達の項目を「ついで」に実装しないこと自体が成果物

---

## 設計原則（第2回の10箇条を実コード検証の結果で改訂。**太字**が新規・変更点）

1. **評価軸の追加は1本道のみ**: 取込（profile/ALLOWED_TAGS）→ domain純関数（traffic/difficulty）→
   **共通合成関数（T43後は1箇所）**→ RoutePreference/YAML → AttributeRepositoryメソッド＋
   ファサード対称委譲 → フロントは**evaluationAxes/staticAttributeLayersのカタログ編集だけ**。
   エンジンファイルに軸固有の知識を書かない
2. **数値定数（半径・閾値・上限）は必ず片側がもう片側をimportする。**「◯◯と揃える」という
   コメントで2箇所に同じ値を書くことを禁止する（R-3のstop半径15mが根拠）。**この制約は
   「完全に同じ値」に限らない。四則演算等で導出できる関係（例: 帯幅＝トラック数×
   オフセット間隔＋自身の太さ）も同様に、値を手計算した結果を独立した定数として書くのでは
   なく、相手側の定数から計算式で導出する**（2026-08-20、MapView.tsxの
   `SECONDARY_AXIS_CASING_WIDTH`〔1次素材線の並列オフセット帯幅と一致させる必要がある〕が
   手計算結果〔7〕を独立した定数として直書きしており、オフセット間隔や素材本数
   （`ROAD_MATERIAL_TRACK_LAYER_IDS`の要素数）を変えても追従せず、下敷きの縁が帯の外側へ
   はみ出す／内側に余るというズレを黙って再発させていたことが根拠。ユーザー指摘
   「オフセット、カーシングの幅は重ねる線が3本から変わっても揃うようにして」「なるべく
   ベタで書かず、揃える制約があるものは連動させて欲しい」を受け、計算式へ改めた）
3. スキーマ変更はmigrations/の番号付きSQLのみ。create_tablesへのALTER追記禁止（維持）
4. フォールバック経路へ新機能を実装しない。**T22撤去後はこの原則自体を削除する**（維持→期限付き）
5. タイルプロパティを変えたら世代ペアを同一コミットで上げる。手動同期ペアの新設は
   ドリフト検知テストと同時のみ（維持）
6. 共通化の判断基準は「変更理由が同じか」だけ。見た目の類似（両エンジンの
   _build_segment_detailsのデータ配線部分等）では統合しない（維持）
7. Repositoryファサードには個別リポジトリ実装後、同じ流儀でフラット委譲を対称追加する
   （維持。P1で規約どおり運用された実績を確認）
8. **UIの語彙表（ラベル・色・凡例）はカタログファイルにのみ書く。**コンポーネント内に
   Recordリテラルの対訳表を作らない。研究UI（ComparisonPanel等）も一般UIと同様に
   カタログから列挙生成する（R-4/R-7が根拠）
9. **page.tsx / MapView.tsxへの追記は閾値監視つきで許可する**: 当初の閾値（静的レイヤー+2種類
   またはMapView 1,200行）は決めておいた2点（宣言的レイヤー登録・useStoredState抽出）ともに
   消化済み（T47）。T91（2026-08-17）で再設定した閾値「MapView.tsx 1,800行」にT123
   （2026-08-18）で到達・解消し、1,654行へ縮小。「3つ目のレシピ軸のMapView内ミラー追加」
   条件はT130（2026-08-18、道路適正・自動車密度の2軸を同時追加）で到達し、KEEP（分割
   しない）と判断のうえ「5つ目のレシピ軸のMapView内ミラー追加」へ繰り上げ済み
   （詳細はR-6参照）。「STATIC_OVERLAY_LAYERS 10種」条件はT145b（2026-08-19、レジストリ
   駆動のramp軸自動生成）後に到達したが、内訳がramp軸の自動合流によるものでMapView.tsx側の
   手書きコスト増加を伴わなかったため、T157（2026-08-19）でカウント方式を
   「手書きSTATIC_OVERLAY_LAYERS（ramp軸を除く）10件」「bespoke種の軸3件目」へ再定義した
   （詳細はR-6参照）。新閾値「MapView.tsx 2,000行」「手書きSTATIC_OVERLAY_LAYERS
   （ramp軸除く）10件」「bespoke種の軸3件目」「5つ目のレシピ軸のMapView内ミラー追加」の
   いずれかに達したら、そのとき改めて対応（分割要否を含む）を判断する。
   **page.tsxにも独立した閾値を新設する**（2026-08-18、
   複雑度レビューF-3）: 「useState+useStoredState合計40件到達」または「1,300行到達」で、
   レイヤー可視性系・研究モード系のグルーピング（useReducer化 or レシピ軸単位のカスタム
   フック化）を判断する。2026-08-18時点の実測は38件・1,148行（前回34件・1,065行から
   増加中、いずれも未到達）
10. 「何もしない」を明示的な判断として記録し、DEFERには必ずトリガー（可能なら日付）を付ける。
    トリガー未到達の項目を「ついで」に実装しない（維持。T22の2026-08-29が好例）
11. **空間JOINを含むSQLは`&&`前置（またはKNNの`ORDER BY <-> LIMIT`）で必ずGiST索引を
    使わせる。`ST_DWithin(geom::geography, ...)`単体をJOIN条件にしない。**
    geographyキャストを挟むとPostGISプランナがgeometry型GiST索引を認識できず、
    全組み合わせをJoin Filterで評価する（T21以前の`_NEAREST_SURFACE_SQL`、T51の
    `match_designations.py`、T64の`_STOP_POI_COUNTS_SQL`等4クエリで同型の劣化を実測）。
    新規の空間JOINを書くときは`_INTERSECTION_COUNTS_SQL`（`&&`前置の先例）を必ず参照する
12. **地図アプリとして地図表示エリアを最大限確保することを優先する。**
    UI文言（ラベル・説明文・凡例・ポップアップ）は表示幅を圧迫しないよう簡潔にする:
    全角括弧「（）」ではなく半角角括弧`[]`を使う（同じ情報量でも表示幅が狭い）、
    可能なら共通語の重複表現を割愛する（例:「緊急輸送道路 かつ 重要物流道路」→
    「緊急輸送 かつ 重要物流道路」のように末尾の共有語へ寄せる）。パネル・ポップアップ・
    凡例のいずれも、地図そのものの視界を削ってまで情報量を増やさない
    （T104: 地図上の凡例内訳ポップアップでの文言見切れ修正、ユーザー指摘を機に明文化）
13. **原則1（評価軸の追加は1本道のみ）は、`dedicated_way_value_layer`軸
    （wind/gradient等、専用のway_id→値配信レイヤーを持つ軸、T405/T423由来）にも同様に
    適用する。フロント側に軸固有のファイル・関数・定数・propを新設してはならない**——
    feature-stateキー・color expression（しきい値・配色）・redraw再適用・
    interactiveLayerIds所属・環境グループのgridFill計算は、いずれも軸スタジオのデータ
    （`dedicated_way_value_layer=true`の軸id一覧・`shape`・`display_thresholds_override`）
    から導出する汎用機構1つが持ち、軸ごとの手書き複製を作らない。物理量の計算式
    （wind_penalty等）はbackendのみが持ち、フロントで再実装しない。**新しい軸を追加する
    ときフロントのコード変更が一切不要（軸スタジオでの登録のみ）であることを完了条件と
    する。**（2026-08-31、windAxisPenalties/gradientAxisValuesという軸ごとに別名のprop・
    `windPenalty.ts`のbackend式JS移植・`WIND_AXIS_THRESHOLDS`という軸スタジオから独立した
    ハードコード定数、という3つの症状が同一の原因（軸ごとに専用実装を作り込む設計）で
    あるとユーザーが繰り返し指摘し明文化。個別修正ではなくこの原則自体の欠落が根本原因
    だったため、原則1の対象を拡張する形でここへ追加した）
