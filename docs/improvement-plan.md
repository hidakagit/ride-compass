# 改善実行計画

RideCompassのタスク台帳。**1行が1タスク**で、持つのは状態・リンク・タイトル・規模だけ。
未完了のものには着手してよい条件を`— トリガー: …`で添える。背景・対応方針・実装メモ・
検証結果は[docs/tasks/](tasks/)配下の`Txxx.md`（タスク番号1件=1ファイル）にあり、
**ここを読んで分かるのは「何が残っているか」だけ**——判断の中身はタスク側にある。

進捗はこのファイルのチェックボックスで管理する。起票・完了の手順は
[workflow.md](workflow.md)、タスク番号の採番と衝突時の振り直しはCLAUDE.md
「作業ツリーの安全」節。節見出しはタスクのテーマ分類で、日付は起票のきっかけが
起きた時点を表す。

2026-08-23棚卸より前の完了タスクの実施記録は[improvement-plan-archive/](improvement-plan-archive/)
にある（索引は[README](improvement-plan-archive/README.md)）。番号が重複した実績がある
T317・T318は、2件目のリンク先が`Txxx-2.md`になっている。

## バックエンド一時的な到達不能の調査（2026-08-17・ユーザー報告）

- [x] [T105](tasks/T105.md) 地図をグリグリ操作した直後にバックエンドへ到達できなくなる事象の原因特定 規模S〜M
- [x] [T259](tasks/T259.md) 20kmルート生成が本番で常に失敗する事象の根本原因を特定 規模S
- [x] [T261](tasks/T261.md) 大規模な冷パスリクエストで本番バックエンドプロセスがクラッシュ→自動復旧する事象 規模不明
- [x] [T262](tasks/T262.md) 冷パスのメモリ・CPU削減（Pydantic依存の解消、T261対応方針2） 規模M
- [x] [T263](tasks/T263.md) backendをOracle Cloud VM（DBと同居）へ移行 規模L
- [x] [T264](tasks/T264.md) 冷パスのステージ別ログ追加＋closure_ms削減 規模S

## テストスイート実行効率化の検討事項（2026-08-18・フロントvitestタイムアウト調査より）



- [ ] [T127](tasks/T127.md) 日本全国データ取込の実現可能性検証〔容量・所要時間〕 規模不明 — トリガー: 全国展開の意思決定

## 評価システムの層構造再設計（2026-08-18・区間評価の一次/二次/三次分離）
- [x] [T145](tasks/T145.md) 地図レイヤーパネルをレジストリ駆動にし、三次（合成コスト）を既定表示レイヤーとして 規模L
- [x] [T145a](tasks/T145a.md) night軸の専用レイヤーを追加する 規模S〜M
- [x] [T266](tasks/T266.md) 0次ハードフィルタをAPI・ベクトル化計算パスへ配線する 規模M

## 動的データの追加候補整理（2026-08-22・雷ほか未着手データの棚卸しと起票）
- [ ] [T206](tasks/T206.md) 積雪・凍結情報（JMA「今後の雪」タイル） 規模S〜M — トリガー: 冬季前（毎年11月）またはユーザーからの着手指示
- [ ] [T207](tasks/T207.md) 雷ポテンシャル（CAPE）による延長予報の検討 規模S — トリガー: T204（雷ナウキャスト60分先まで）だけでは見通しが不足するという利用実績・要望が出た時点
- [ ] [T208](tasks/T208.md) 視程・霧情報の導入可否を調査する 規模S — トリガー: 山間部・河川霧発生地域での利用報告、または優先度見直し
- [x] [T209](tasks/T209.md) 黄砂・PM2.5情報の導入可否を調査する 規模S
- [x] [T221](tasks/T221.md) 評価軸のフルレジストリ駆動化＋GUI編集基盤 規模L
- [x] [T222](tasks/T222.md) Overpassライブ経路（`repository`未指定構成）の削除 規模M
- [x] [T223](tasks/T223.md) DEM1A（1mメッシュ）標高データの組み込み可否調査 規模S

## 統合レビュー対応（2026-08-23・review:all第6回の指摘）

- [x] [T224](tasks/T224.md) save_graph再構築経路の32767パラメータ超過を修正し、road_graph APIのエンドツーエンドを実測してT218/T219の完了条件を裏取りする〔P1〕 規模S
- [x] [T225](tasks/T225.md) OpenAPI生成物へpenalty_strength/max_average_grade_percentを反映する〔P1〕 規模S
- [x] [T226](tasks/T226.md) T218/T219/T220後の旧経路残骸を削除する〔P2〕 規模S〜M
- [x] [T227](tasks/T227.md) architecture.mdのT11完了を追従する〔P2〕 規模S
- [x] [T228](tasks/T228.md) 統合レビュー第6回の軽微指摘4件を一括解消する〔P3〕 規模S
- [x] [T229](tasks/T229.md) T219冷パス（タイル分解）のクエリ本数増を実測する 規模S

## 過去記録の全見直しで判明したあいまい残件の明確化（2026-08-23棚卸・ユーザー指示）

- [x] [T230](tasks/T230.md) CI・GitHub Actionsの健全性を確定する（api-contract成否・無償枠・Dependabot稼働） 規模S
- [x] [T231](tasks/T231.md) 設計判断の未確定残件2件を確定して記録する 規模S
- [x] [T232](tasks/T232.md) 検証が保留のまま記録されている残件4件を明確化する 規模S〜M

## 実装・テスト整合性の総点検対応（2026-08-23・review:consistency）

- [x] [T233](tasks/T233.md) CIの`backend`ジョブへPostGIS統合テスト実行環境を追加する〔P1〕 規模S
- [x] [T234](tasks/T234.md) e2eフィクスチャがGenerationConditions等の必須フィールドと乖離していた問題を修正する〔P2〕 規模S
- [x] [T235](tasks/T235.md) backend pytestをpytest-xdistで並列化する〔ユーザー指摘: テスト実行が遅い〕 規模S

## ORS→road_graphエンジン移行の残作業（2026-08-23・ユーザー指示）


- [x] [T242](tasks/T242.md) 本番Oracle DBへのmigration 0013適用（road_graphエンジンが本番で起動不能だったブロッカー解消） 規模S
- [x] [T243](tasks/T243.md) road_graphエンジン専用DBエンジンのcommand_timeout分離 規模S
- [x] [T244](tasks/T244.md) 外部APIクライアントのTTLキャッシュを`cachetools`へ統一 規模S
- [x] [T245](tasks/T245.md) save_graphのDELETE段の性能調査＋ステージ別ログ追加 規模S
- [x] [T246](tasks/T246.md) save_graphのDELETE除外条件を一時テーブル化＋work_mem引き上げ 規模M
- [x] [T236](tasks/T236.md) road_graphエンジンの経路品質比較検証 規模S
- [x] [T237](tasks/T237.md) `/api/routes/preview`のroad_graphエンジン対応 規模S〜M
- [x] [T238](tasks/T238.md) `evaluate_graph`のcar_stress判定ホットパス最適化 規模S〜M

## T221 Stage A先行＋evaluate_graph全面ベクトル化（2026-08-23・ユーザー指示）

- [x] [T239](tasks/T239.md) T221 Stage A: 現行7軸を4テンプレートへ実装移行 規模M
- [x] [T240](tasks/T240.md) `EvaluationService.evaluate_graph`のnumpyベクトル化 規模L
- [x] [T241](tasks/T241.md) 道路グラフの連結性調査（弱連結成分の分断でルート探索が失敗するケース） 規模S〜M
- [x] [T247](tasks/T247.md) `routing_engine`既定値をroad_graphへ切替 規模M

## 統合レビュー第7回の起票（2026-08-23、ユーザー承認済み）

- [x] [T248](tasks/T248.md) road_graph既定エンジンの性能改善（バルクUPSERT最適化＋冷パス体験設計） 規模M〜L
- [x] [T265](tasks/T265.md) 冷パスの体験設計（バックグラウンドウォームアップ・主要エリア事前split・進捗表示） 規模M〜L
- [x] [T256](tasks/T256.md) 都心部（新宿・渋谷）でルート生成が候補0件になる事象の原因調査＋修正 規模S〜M
- [x] [T249](tasks/T249.md) 統合レビュー第7回の軽微指摘一括 規模S

## モバイル画面のスペース有効活用（2026-08-23・ユーザー指示）

- [x] [T250](tasks/T250.md) スマホ上部バーへ出発地点・距離・生成ボタンを集約＋下部タブ再定義 規模S〜M
- [x] [T251](tasks/T251.md) 定番UIライブラリでの現行UI同等再現可否・規模の調査 規模M
- [x] [T252](tasks/T252.md) Phase0: Tailwindの併用導入 規模S
- [x] [T253](tasks/T253.md) Phase1: 点在する小部品の置換＋FloatingPanel→react-rnd 規模S〜M
- [x] [T254](tasks/T254.md) Phase2: アコーディオンをRadix Accordionへ 規模S
- [x] [T255](tasks/T255.md) Phase3: BottomSheet→vaul（断念）、DynamicLayerTimeSlider→Embla Carousel 規模M〜L
- [x] [T257](tasks/T257.md) WBGT数値と気象庁警報・注意報の語彙混同バグを修正する 規模S
- [x] [T258](tasks/T258.md) フロントのfetch()失敗がデバッグログに残らない箇所を横断的に修正する 規模S〜M

## 目論見書による二画面構想の正式化（2026-08-24・ユーザー承認）

「自転車専用道を優先したい」という要望の調査から始まった一連の議論（0次フィルタの
未配線発見→T266起票→重みUI再設計案→二画面分割案→最終形の構想）を、目論見書
（Artifact: `RideCompass 目論見書`、https://claude.ai/code/artifact/ce418e86-3338-410b-9d14-826e00764b78 ）
として取りまとめ、**ユーザーが承認した**（2026-08-24）。骨子:

- **最終形**: 一般ユーザーは研究側で練り上げられた少数の推定軸の重みを調整するだけで
  最適なルーティングが得られる状態へ「蒸留」していく。一般UIの選択肢は増やさず、
  利用実績に基づいて淘汰する。
- **二画面分割**: 「軸を使う人」（一般向けルート設定）と「軸を作る人」（軸スタジオ=
  T221 Stage E相当）を別画面にする。**軸スタジオは既存ページ内のパネルではなく
  独立URLの管理画面として実装する**（ユーザー指示による修正点。URLレベルで切れて
  いる方が権限制御を敷きやすい）。現行メインページの「研究」セクション
  （ResearchPanel・WeightPanel・レシピパネル群）と「開発者」セクション（DebugPanel・
  DebugConsole・SystemStatusPanel）はこの管理画面へ移設する。
- **設計上の歯止め6条**（材料の排他帰属の機械検査／公開済みaxis_id不変・変更は複製＋
  新ID／テンプレート4種の線引き維持／材料の天井の明示／認可境界1箇所・安全側
  デフォルト／DBが追いつくまで挙動を変えない）を実装に埋め込む。

現在地: T221 Stage A〜D完了（DB化・管理API・本番migration適用済み）、T266起票済み。
残るギャップを以下のタスクへ正式分解する。Phase番号は目論見書6章のロードマップに対応。

- [x] [T267](tasks/T267.md) 一般向けルート設定画面の再設計実装（Phase 1） 規模M〜L
- [x] [T268](tasks/T268.md) 材料の排他帰属チェックを計算系レジストリへ移植する（Phase 2前提） 規模S〜M
- [x] [T269](tasks/T269.md) 軸カタログ（axis-catalog.json）のDB追従方式の決定＋実装（Phase 2前提） 規模M
- [x] [T270](tasks/T270.md) 軸スタジオ — 独立URLの管理画面としてT221 Stage Eを実装する（Phase 2本体） 規模L
- [x] [T271](tasks/T271.md) 軸の公開フローと統治ルール（Phase 3） 規模M
- [x] [T272](tasks/T272.md) 管理画面・研究機能の権限制御導入（Phase 3） 規模M
- [x] [T519](tasks/T519.md) 研究モードを一般利用者向けのヘッダーメニューへ再配置し、/admin依存を解消する 規模S〜M
- [ ] [T273](tasks/T273.md) 蒸留 — 一般UIの軸カタログ縮退（Phase 4） 規模S〜M — トリガー: 一般公開の意思決定、およびPhase 3までの利用実績の蓄積
- [x] [T274](tasks/T274.md) 周回ルートの逆回り（反時計回り/時計回り）候補も評価し、良い方を採用する 規模M
- [x] [T275](tasks/T275.md) Tailwind CSSの採否を決定する（現状は未使用のまま依存関係にのみ存在） 規模S
- [x] [T276](tasks/T276.md) registry.py（表示用レジストリ）とAXIS_DEFINITIONS（Stage D）の軸ラベル重複を解消する 規模S
- [x] [T277](tasks/T277.md) 材料カタログをbackend正式レジストリ化し軸コンポーザーへ動的連携する 規模S〜M
- [x] [T278](tasks/T278.md) 地図表示ルール(kind=ramp)の自動導出・軸集合の同期 規模M

## 全体最適レビュー第8回の起票（2026-08-24・ユーザー承認済み）

全ソースコード・DB設計をゼロから再読した総合診断レビュー
（[.claude/commands/review/history/2026-08-24_overall.md](../.claude/commands/review/history/2026-08-24_overall.md)、
対象コミット`fc7bd5a`、総合スコア83/100）の指摘を起票する。起票案A〜Fに加え、
ユーザー指示「知見として見つけたものもタスク化・掘り下げするべきものがないか再チェック」を
受け、レポート本文に留めていた知見4件（T285〜T288）もトリガー付きで正式起票した。

- [x] [T279](tasks/T279.md) OpenAPI生成物ドリフトの解消＋CI状態確認＋コミット前検知の機械化判断〔P1〕 規模S
- [x] [T280](tasks/T280.md) 材料供給の1本道短縮（軸スタジオの「材料の天井」の構造対策）〔P2〕 規模M〜L
- [x] [T281](tasks/T281.md) 派生データ鮮度の段階対応（依存DAG文書化→統合エントリポイント→鮮度台帳）〔P2〕 規模S→M
- [x] [T282](tasks/T282.md) Repositoryファサード委譲33本 — R-8トリガー「30本超で再検討」発火の判断記録〔P2〕 規模S
- [x] [T283](tasks/T283.md) `road_graph_use_repository`設定の名称・既定値の再考〔P3〕 規模S
- [x] [T284](tasks/T284.md) page.tsx閾値発火前の分割方針の事前確認〔P3〕 規模S
- [x] [T375](tasks/T375.md) page.tsxの気象・動的レイヤー系state（13件）をカスタムフックへ抽出 規模M
- [x] [T285](tasks/T285.md) 表示系レジストリの縮退 — 軸カタログのランタイム一本化〔P3〕 規模M〜L
- [x] [T286](tasks/T286.md) architecture.mdの経緯記述をdecisions/へ追い出す第2弾〔P3〕 規模M
- [ ] [T287](tasks/T287.md) road_nodes/road_edgesのtext型PKの容量・性能再評価〔P3〕 規模S — トリガー: T127（全国データ取込）の意思決定時に容量試算へ含める
- [ ] [T288](tasks/T288.md) AXIS_DEFINITIONS push型更新のマルチワーカー対応〔P3〕 規模S〜M — トリガー: 複数メンバーが触る状態にプロダクトが成長した時点
- [x] [T289](tasks/T289.md) 一方通行（一次属性）を観測グループの独立レイヤーとして追加する 規模S〜M
- [x] [T290](tasks/T290.md) MVTタイルに焼き込み済みだが材料未登録の生データをMATERIAL_CATALOGへ網羅登録する 規模M
- [x] [T291](tasks/T291.md) ~~car_stress軸のcycleway補正をbicycle_infra（6値）ベースへ精密化する~~ 規模L
- [x] [T292](tasks/T292.md) 推定軸に「内部軸→公開軸」の階層構造を導入し、一次材料の宣言的組み立てだけで推定軸を再現・新設できる基盤を作る 規模XL
- [x] [T294](tasks/T294.md) 本番DBがmigration 0017・0018未適用のまま起動していた事象の発見・修正 規模S
- [x] [T293](tasks/T293.md) 周回ルートの採用向き（順回り/逆回り）を地図上へ矢印で明示する 規模S〜M

## 全体最適レビュー第9回の起票（2026-08-25・ユーザー承認済み）

全ソースコード・DB設計を一から再読した総合診断レビュー
（[.claude/commands/review/history/2026-08-25_overall.md](../.claude/commands/review/history/2026-08-25_overall.md)、
対象コミット`8cea9ee`、総合スコア86/100、前回83から+3）の指摘を起票案A〜Dとして正式起票する。
前回（第8回）が最重要提言とした「材料供給への投資」はT290・T292で消化され、
前回P1（OpenAPIドリフト）もT279のpre-commitフックで再発ゼロを維持している。
今回の最重要指摘は、レビュー期間中に実際に発生した**T294（本番DB migration
0017/0018未適用、4回目の同クラス障害）の恒久対策が宙に浮いている**という点（F-1→T295）。

- [x] [T295](tasks/T295.md) 軸定義DB読み込みの整合検証（未知材料参照の検出・axis_id集合差分の常時ログ）〔P2〕 規模S〜M
- [x] [T296](tasks/T296.md) 軸スタジオでの軸id⇔材料idの名前空間衝突ガード追加〔P3〕 規模S
- [x] [T297](tasks/T297.md) car_stressランプ表示のmapping未登録highway（footway/path等）の意味論確定〔P3〕 規模S〜M
- [x] [T298](tasks/T298.md) T292削除物を参照する残骸コメントの訂正・種別の削除条件明文化〔P3〕 規模S
- [x] [T299](tasks/T299.md) Tailwind CSS + Radix UI + components/ui/ のデザイン基盤を新設する 規模M

## ルート詳細タブのモバイルUI再構成（2026-08-25・ユーザー指示）

- [x] [T300](tasks/T300.md) 「開発者」タブ廃止＋「ルート詳細」タブの設定/結果2分割〔P3〕 規模M

## 管理者画面（軸スタジオ）の改善（2026-08-25・ユーザー指示）

- [x] [T301](tasks/T301.md) `/admin`画面のモバイル対応（レスポンシブ未実装の解消） 規模S
- [x] [T302](tasks/T302.md) 軸の公開→未公開（unpublish）を追加し、既存軸の削除を解禁する 規模M
- [x] [T303](tasks/T303.md) route_preferenceのキー整合チェックを生成リクエスト組み立て時にも持たせる〔P3〕 規模S〜M
- [x] [T304](tasks/T304.md) 軸スタジオのUX改善（編集モーダル化・説明文追加・研究モードの重み整理） 規模M
- [x] [T305](tasks/T305.md) 軸スタジオの使いにくさ（二重ログイン・axis_id・分類・z-index） 規模M

## ルート設定画面のカテゴリ表示撤去とプロファイル構想（2026-08-25・ユーザー指示）

- [x] [T306](tasks/T306.md) ルート設定画面のカテゴリ別グルーピング表示を撤去 規模S
- [ ] [T307](tasks/T307.md) プリセット（プロファイル）機能のマスタ化 規模M〜L
- [x] [T308](tasks/T308.md) 推定軸の地図表示自動連動 規模M〜L
- [x] [T309](tasks/T309.md) ルート詳細レスポンス（RouteSegmentDetail/RouteCandidate）の軸別内訳を汎用化 規模M
- [x] [T310](tasks/T310.md) 軸スタジオへ地図チップ表示要素（アイコン・略称・地図パネル説明文・代役案内・地図ramp閾値上書き）の登録機能を追加 規模M〜L
- [x] [T311](tasks/T311.md) 軸スタジオを開くと500エラーになる不具合の調査・恒久対策 規模S
- [x] [T312](tasks/T312.md) 未公開の内部軸がルート設定画面に漏れる不具合の恒久対策（T311フォローアップ） 規模S
- [x] [T313](tasks/T313.md) 非バランスプリセット選択時に重み配分が薄まる不具合を修正 規模S
- [x] [T314](tasks/T314.md) デプロイ中の接続切断でルート生成が失敗する不具合の恒久対策 規模S
- [x] [T315](tasks/T315.md) CORS_ALLOWED_ORIGINS不一致でルート生成が即時失敗する不具合の恒久対策 規模S
- [x] [T316](tasks/T316.md) route_preference.yaml撤廃（既定重みの情報源をAXIS_DEFINITIONSへ一本化） 規模S
- [x] [T317](tasks/T317.md) 動的グループを「地図の見え方」パネルから撤去し、説明文を地図上チップへ移設 規模S
- [x] [T318](tasks/T318.md) 軸スタジオに「地図上にアイコン表示」ON/OFFを追加し、proxy_hintを撤去 規模S〜M
- [x] [T382](tasks/T382.md) road_graphエンジンのprepare_msが距離拡大に伴い異常に遅い（30kmで54.5秒） 規模S
- [x] [T379](tasks/T379.md) debug_modeのランタイム切替とログ取得を管理APIから行えるようにする 規模S〜M
- [x] [T319](tasks/T319.md) 全軸を軸スタジオで非公開にしても、ルート設定パネルに既存7軸が残り続ける不具合を修正 規模S
- [x] [T320](tasks/T320.md) 既存7軸ハードコーディングの全面再監査と修正（T319で見落とした残り分） 規模M
- [x] [T321](tasks/T321.md) 全ソース対象のデッドコード監査と修正 規模L
- [x] [T322](tasks/T322.md) 軸スタジオの「カテゴリ値」テンプレートをcategorical材料（highway/bicycle_infra等）にも対応させる 規模S〜M
- [x] [T323](tasks/T323.md) 軸の削除時、他軸から材料として参照されている場合にその事実と影響を明示する 規模S〜M
- [x] [T324](tasks/T324.md) 軸スタジオの変換テンプレート4択の説明文を、専門知識のない一般ユーザー向けに言い換える 規模M
- [x] [T325](tasks/T325.md) 「車の圧迫感」軸のサマリ表示で、他axis_id参照材料をaxis_idのlabelへ解決する 規模S
- [x] [T326](tasks/T326.md) 軸スタジオ「カテゴリ値」テンプレートの選択肢ラベルを、多値対応後の実態に合わせて修正 規模S
- [x] [T327](tasks/T327.md) 軸スタジオの折れ点(breakpoints)編集欄に、スコアの向き（走りやすさの規約）を明示する 規模S
- [x] [T332](tasks/T332.md) 軸スタジオをウィザード形式へ再設計し、専門知識のない一般ユーザー向けに用語を平易化する（T324/T326/T327を統合実装） 規模L
- [x] [T328](tasks/T328.md) テスト品質監査で発見した現存する実装バグ4件の修正 規模S
- [x] [T329](tasks/T329.md) テスト実行コストの是正 規模S
- [x] [T330](tasks/T330.md) テストカバレッジ欠落の是正（影響度「高」・複数レビューで確認済み） 規模M
- [x] [T331](tasks/T331.md) テストカバレッジ欠落の是正（影響度「中」） 規模L
- [x] [T333](tasks/T333.md) axis-catalog.json（categorical材料のcategories辞書）の生成順序がDB接続可否で非決定になる 規模S〜M
- [x] [T334](tasks/T334.md) 地図チップ「表示する項目を選ぶ」設定パネルの各項目に個別の情報アイコンを追加する 規模M
- [x] [T335](tasks/T335.md) CI(backend)のtest_match_designations.pyがCI環境（PostGIS 16）でだけ失敗する 規模S〜M
- [x] [T336](tasks/T336.md) bicycle_infra材料をcar_stress_bicycle_infra_adjustment内部軸から正規化フラグ材料群へ置き換える 規模M
- [x] [T337](tasks/T337.md) cycleway_class材料の未使用状態を整理する 規模S
- [x] [T338](tasks/T338.md) designation材料（3値カテゴリ）の未使用状態を整理する 規模S
- [x] [T339](tasks/T339.md) 材料抽出（extractor）の完全宣言駆動化 規模M〜L
- [x] [T340](tasks/T340.md) highway/surface/smoothnessの値一覧・ラベル提示（軸スタジオの値入力UX改善） 規模M
- [x] [T341](tasks/T341.md) 地図表示ロジックの定義場所をSQL側へ一本化し、分離原則をdocs/architecture.mdへ反映 規模S
- [x] [T342](tasks/T342.md) 材料正規化方針を踏まえた軸スタジオUIの見直し検討 規模S
- [x] [T343](tasks/T343.md) compute_edge_costs_bulkがextractor未設定の材料を参照する軸でKeyErrorする 規模S
- [x] [T344](tasks/T344.md) CIのbackendジョブがosmium未インストールでtest_import_pbf.py/test_pbf_source.pyの収集に失敗する 規模S
- [x] [T345](tasks/T345.md) 軸スタジオ「値ごとのスコア」操作の改善（材料説明アイコン・重みの相対比較・スコア向き修正） 規模M
- [x] [T346](tasks/T346.md) 軸スタジオ: ウィザード最終ステップの暗黙送信バグ修正・軸同士の線形結合(nX+mY)テンプレート修正 規模M
- [x] [T347](tasks/T347.md) bicycle_infra材料・地図レイヤー・classify_bicycle_infrastructureの完全削除、代替推定軸の新設 規模L
- [x] [T348](tasks/T348.md) 組み込み評価軸のDB投入（migration）を`axis_definitions.py`から自動生成し、手書き二重管理を解消 規模M
- [x] [T349](tasks/T349.md) T348（第三案）を差し戻し、軸定義DB同期のフォールバックを廃止しfail-fast化（オプションAへ） 規模M
- [x] [T350](tasks/T350.md) axis_definitionsを全14軸DB専有化し、Python literalを撤去（フル版オプションA） 規模XL
- [x] [T351](tasks/T351.md) 派生データの世代管理・Raw→Derived系譜追跡の強化 規模M〜L
- [x] [T352](tasks/T352.md) axis_idハードコード分岐を宣言的フィールドへ汎用化（時刻依存・地図色分け対応） 規模M
- [x] [T353](tasks/T353.md) 内部軸の出力が正規化されないまま他軸の材料として参照される（軸参照と材料正規化方針の不整合） 規模M
- [x] [T354](tasks/T354.md) docs/architecture.mdのAxisComposer.tsx記述をT332後のウィザード構成へ更新 規模S
- [x] [T355](tasks/T355.md) AxisComposer.tsxの規模ウォッチ閾値を新規登録し、churn沈静化後にshape種別ごとの分割を検討 規模S
- [x] [T356](tasks/T356.md) レビュー履歴ファイル`history/2026-08-26_complexity.md`の不在について記録を整合させる 規模S
- [x] [T357](tasks/T357.md) road_graph_repository.py・road_graph_engine.pyの規模ウォッチ閾値を新規登録 規模S
- [x] [T358](tasks/T358.md) T350削除禁止ガードの回帰テストをwind・gradient軸まで拡張 規模S
- [x] [T359](tasks/T359.md) 王子-荒川ルート検索がヒットしない問題への対応（footway/path欠損の穴埋め・共用歩行者自転車道材料の新設） 規模S
- [x] [T360](tasks/T360.md) fresh bootstrap時にcar_stress_bicycle_infra_adjustmentが復活する不整合の解消 規模S〜M
- [x] [T361](tasks/T361.md) axis_definitionsのfresh bootstrapをmigrationシードからDBスナップショット取込みへ転換（migration/API二重管理の恒久解消） 規模M〜L
- [x] [T377](tasks/T377.md) axis_definitionsスナップショットを本番/devの実際の内容へ再生成する 規模S
- [x] [T378](tasks/T378.md) 地図オーバーレイの▼ページ送り判定が、気象タイムラインパネル表示中の占有高さを考慮しておらず、末尾チップがパネルの裏に隠れる不具合を修正 規模S
- [x] [T362](tasks/T362.md) 本番DBで6公開軸がis_published=falseになっていた不整合の発見・修正 規模S
- [x] [T363](tasks/T363.md) road_graphエンジンの出発点ノード選択が非決定的で、同一条件でも全8方位が同時に失敗することがある 規模M
- [x] [T364](tasks/T364.md) 経由地（中継地）を指定できるルート生成への拡張 規模M〜L
- [x] [T365](tasks/T365.md) 目的地（終点）を指定できるルート生成への拡張・ルート結果のクリアボタン 規模M
- [x] [T366](tasks/T366.md) 出発地点を地図タップで手動指定できるようにする 規模M
- [x] [T367](tasks/T367.md) 軸スタジオ由来の推定軸「自転車インフラ」を地図上へ自動表示できるようにする 規模M
- [x] [T368](tasks/T368.md) 出発地点表示の文字を廃止しピンの色分けだけで伝えるよう簡素化 規模S
- [x] [T369](tasks/T369.md) 推定グループの軸タイルを観測グループと同じ見た目に統一・凡例パネルの画面右端はみ出しを解消 規模S
- [x] [T370](tasks/T370.md) 推定グループを横スクロールへ変更・chipRow/estimatedFlatRowのスクロールバーを非表示化 規模S
- [x] [T371](tasks/T371.md) chipRow/estimatedFlatRowへtouch-actionを明示しスクロール不能を修正 規模S
- [x] [T372](tasks/T372.md) 出発地点マーカーをドラッグ移動可能にし、現在地アイコンと統一・地図マーカーのtouch-action漏れを修正 規模S
- [x] [T373](tasks/T373.md) chipRow/estimatedFlatRowをJSポインタドラッグによる手動スクロールへ切替（アイコン上からのドラッグでもスクロール可能に） 規模S
- [x] [T374](tasks/T374.md) chipRow/estimatedFlatRowをスクロール／ドラッグ廃止し、ページング送りボタン方式へ再設計 規模S
- [x] [T376](tasks/T376.md) 地図オーバーレイの`pointer-events: auto`がボタン以外の隙間ごとタッチを奪い、地図パン操作ができなくなる不具合を修正 規模S
- [x] [T380](tasks/T380.md) 推定グループ展開時、地図オーバーレイの▼縦送りボタンがチップ列から水平方向にずれて浮く不具合を修正 規模S
- [x] [T381](tasks/T381.md) 地図オーバーレイの▲▼/◀▶ページ送りボタンに長押し連続送りを追加し、連打による誤タップ地図ズームを軽減 規模S
- [x] [T383](tasks/T383.md) 常設天候ヘッダーで、天候の数値を警報バッジより優先して常時可視にする 規模S
- [x] [T384](tasks/T384.md) ロードバイク走行に有用なOpen-Meteo変数の棚卸しと表示要否の判定（調査） 規模S
- [x] [T385](tasks/T385.md) 常設天候ヘッダーに「今日の見通し」二次パネル＋天気アイコン化を追加 規模M
- [x] [T317](tasks/T317-2.md) 動的グループを「地図の見え方」パネルから撤去し、説明文を地図上チップへ移設
- [x] [T318](tasks/T318-2.md) 軸スタジオに「地図上にアイコン表示」ON/OFFを追加し、proxy_hintを撤去
- [x] [T386](tasks/T386.md) T265（ルート生成の非同期ジョブ化）コードレビュー指摘対応 規模M
- [x] [T387](tasks/T387.md) JMA気象データ連携基盤の新設（Redis導入）とPostGIS揮発データのRedis移行 規模L
- [ ] [T388](tasks/T388.md) job_registryのマルチワーカー対応〔P3〕 規模S — トリガー: 複数メンバーが触る状態にプロダクトが成長した時点
- [ ] [T389](tasks/T389.md) MSM（5kmメッシュ）GRIB2パーサーの本実装 規模M〜L — トリガー: JMBSC契約費用（月額約13,500円＋初回50,000円）を払ってでも導入する段階になった時点
- [x] [T390](tasks/T390.md) road_graph評価ホットパスのis_split_up_to_date・get_edges_with_geometryをRedis cache-aside化 規模M
- [x] [T391](tasks/T391.md) generate_loopsの8方位並列trace_loopが共有するGraphServiceのAsyncSessionを保護 規模S
- [x] [T392](tasks/T392.md) タイル材料一式（graph_material_cache）のRedis複製化 規模M
- [x] [T393](tasks/T393.md) 本番Redisにmaxmemoryと退避ポリシーが未設定〔P2〕 規模S
- [x] [T394](tasks/T394.md) GraphService.get_way_tagsが未使用の可能性〔調査のみ〕 規模S

## 静的道路属性データソースの追加検討（2026-08-29・道路交通センサス活用調査）

- [x] [T395](tasks/T395.md) 令和3年度道路交通センサスデータの活用可否調査〔調査のみ〕 規模不明

## 軸スタジオの合成ロジック・UI再設計（2026-08-29）

- [x] [T396](tasks/T396.md) 軸スタジオの評価軸合成ロジックを4テンプレートから2プリミティブ+合成へ再設計 規模M
- [x] [T397](tasks/T397.md) 軸スタジオUIの3カード再設計（なめらか/ぴったり/かけあわせ） 規模M

## 地図×評価軸の連動モデル再設計（2026-08-29〜30）

- [x] [T400](tasks/T400.md) 地図×評価軸の連動モデル再設計（パネル構成・動的材料の二重表現・display_override廃止） 規模L
- [x] [T401](tasks/T401.md) RouteScorerをdistance/difficultyの2指標へ単純化 規模S〜M
- [x] [T402](tasks/T402.md) Route.axis_difficulties新設とBottomSheetルート全体プロファイル 規模M
- [x] [T403](tasks/T403.md) ルート区間クリック内訳（小型チャート） 規模S〜M
- [x] [T404](tasks/T404.md) display_override廃止（JS変換ロジック拡張＋軸スタジオの色分けしきい値編集） 規模M〜L
- [x] [T405](tasks/T405.md) 動的要素の二重表現（風の環境/評価軸表示、Redis経由way_id→値配信） 規模L
- [x] [T406](tasks/T406.md) パネル構成再編（道路/評価軸/環境/スポットの4チップ・3排他ドメイン） 規模M〜L
- [x] [T411](tasks/T411.md) 動的＋向きあり要素の「way_id→値」配信を汎用化する検討 規模S〜M
- [x] [T413](tasks/T413.md) サイドバー「地図の見え方」パネルの語彙をチップ側の4分類へ統一するか検討 規模S〜M
- [x] [T414](tasks/T414.md) 動的材料の状態別表現契約を確立し、風（第1の具体例）を訂正後の契約どおり作り直す 規模M
- [x] [T415](tasks/T415.md) pytest-xdist並列実行時のDB競合フレークを調査する 規模S
- [x] [T416](tasks/T416.md) 洪水キキクル（`.pbf`形式）の実装検討 規模S〜M
- [x] [T417](tasks/T417.md) 評価軸チップの展開方向を横並びから縦並びへ統一 規模S
- [x] [T418](tasks/T418.md) 評価軸チップを地図UIから撤去し、ルート設定/ルート結果パネルへ統合する 規模M〜L
- [x] [T419](tasks/T419.md) ルート設定・ルート結果パネルのレイアウト見直し（地図を圧迫する「遊び」を削る） 規模S〜M
- [x] [T421](tasks/T421.md) ルート結果パネルの候補サマリ・色分けモード・おすすめ度説明を評価軸カタログ駆動へ見直す 規模S〜M
- [x] [T431](tasks/T431.md) RouteCandidateのレガシー個別フィールド（stop_density等9個）を末端消費者ゼロ化後に廃止するか検討 規模S
- [ ] [T422](tasks/T422.md) 「環境」グループに合成面データ用のプレースホルダー構造を用意する 規模S — トリガー: 環境グループ向けの合成面データを追加する判断をした時点
- [x] [T423](tasks/T423.md) 勾配（gradient）を評価軸として実装する 規模M
- [x] [T409](tasks/T409.md) axis_definitions.display_override列の削除 規模S

## 地図×評価軸の再設計セッションからの派生タスク（2026-08-29〜30）

- [x] [T398](tasks/T398.md) 風グリッド（Open-Meteo）のキャッシュをSQLiteからRedisへ移行する検討 規模S
- [x] [T399](tasks/T399.md) 標高データを永続化する設計検討 規模S

## T387続き: 無償範囲で追加できるJMAデータの実装（2026-08-30）

- [x] [T407](tasks/T407.md) 降水短時間予報（気象庁rasrf）の実装 規模M
- [x] [T408](tasks/T408.md) 線状降水帯予測マップ（気象庁sjfcstmap）の導入可否調査 規模S
- [x] [T410](tasks/T410.md) キキクル（危険度分布：土砂・大雨・浸水）+線状降水帯予測マップの実装 規模M
- [x] [T412](tasks/T412.md) JMA動的タイル系レイヤーのバックエンド経由化（プロキシ+キャッシュ） 規模M
- [x] [T420](tasks/T420.md) キキクル+線状降水帯予測マップを既定ONにする 規模S
- [x] [T432](tasks/T432.md) 動的気象レイヤーの一般化+防災グループ再編・降水グループ拡張 規模L

## ゼロベース網羅レビュー対応（2026-08-30・code-review max×9分割の指摘）

`review-zero-base`ワークツリーでmasterのfull-tree（839ファイル・約14万行）を9領域へ分割し、
各領域を専用エージェントが8観点（正しさ×3・再利用性・簡素化・効率性・抽象度・CLAUDE.md規約）で
網羅レビューした。指摘86件の全件詳細は[docs/zero-base-review-2026-08-30.md](zero-base-review-2026-08-30.md)。
個別のタスクエントリへは転記せず同ドキュメントへリンクする（P1以下は同期漏れを避けるため）。

- [x] [T424](tasks/T424.md) 材料カタログ0件時にAxisComposer（軸スタジオ）がクラッシュする不具合を修正 規模S
- [x] [T425](tasks/T425.md) ゼロベース網羅レビューのP1指摘13件の対応検討 規模M
- [x] [T426](tasks/T426.md) ゼロベース網羅レビューのP2/P3指摘72件の棚卸し 規模M〜L
- [x] [T463](tasks/T463.md) ゼロベース網羅レビュー§1(backend/domain)の残指摘8件対応 規模M
- [x] [T464](tasks/T464.md) ゼロベース網羅レビュー§2(backend/infrastructure)の残指摘5件対応 規模S〜M
- [x] [T465](tasks/T465.md) ゼロベース網羅レビュー§3(MapView.tsx)の残指摘6件対応 規模M
- [x] [T466](tasks/T466.md) ゼロベース網羅レビュー§4(Map/その他)の残指摘8件対応 規模M
- [x] [T467](tasks/T467.md) ゼロベース網羅レビュー§5(backend/api+batch)の残指摘12件対応 規模M〜L
- [x] [T468](tasks/T468.md) ゼロベース網羅レビュー§6(frontend/app)の残指摘5件対応 規模S〜M
- [x] [T469](tasks/T469.md) ゼロベース網羅レビュー§7(backend/services)の残指摘6件対応 規模M
- [x] [T470](tasks/T470.md) ゼロベース網羅レビュー§8(frontend hooks/services/lib)の残指摘7件対応 規模M
- [x] [T471](tasks/T471.md) ゼロベース網羅レビュー§9(frontend components、Map除く)の残指摘7件対応 規模M
- [x] [T427](tasks/T427.md) architecture.mdの記述整合（サイドバー4分類・軸スタジオテンプレート数） 規模S
- [x] [T428](tasks/T428.md) architecture.mdの経緯記述をdecisions/へ抽出（第3弾） 規模M
- [x] [T429](tasks/T429.md) `pytest -m "not postgis"`が実は何もフィルタしていない問題を修正 規模S
- [x] [T430](tasks/T430.md) MapView.tsxのKeep List閾値更新 規模S
- [x] [T433](tasks/T433.md) ルート結果の色分けモード既定値のハードコードを解消 規模S
- [x] [T434](tasks/T434.md) ルート結果の色分けモードを評価で有効にした軸だけに動的に絞り込む 規模S

## UI/UXユーザーレビュー対応（2026-08-30・review:ui、一般ユーザー操作フロー集中回の起票、ユーザー承認済み）

対象範囲は目的地指定→ルート生成→ルート軸調整→軸の反映内容確認→ルート再生成→ルート比較の
一連の操作フロー。詳細は[history/2026-08-30_ui.md](../.claude/commands/review/history/2026-08-30_ui.md)参照。

- [x] [T435](tasks/T435.md) RouteSettingsPanelの重みスライダーがデスクトップサイドバーで幅0pxに潰れる不具合を修正 規模S〜M
- [x] [T436](tasks/T436.md) RouteAxisProfileの難易度バーが未描画になる不具合を修正 規模S
- [x] [T437](tasks/T437.md) 目的地モードの空状態案内文をルート生成モードに応じて出し分ける 規模S
- [x] [T438](tasks/T438.md) 一般ユーザー向け画面の文言から「軸スタジオ」の露出を除去する 規模S
- [x] [T439](tasks/T439.md) モバイルでルート生成完了時に「ルート結果」タブへ視覚的に誘導する 規模S〜M
- [x] [T440](tasks/T440.md) ルート結果・ルート設定パネルの色分けを軸スタジオへ完全同期する 規模L

## 統合レビュー第2回の起票（2026-08-30、review:all、ユーザー承認済み「P1だけでなく指摘全て起票して」）

T414自己是正〜T440（51コミット）を対象とした2回目の統合レビュー
（[history/2026-08-30_all_2.md](../.claude/commands/review/history/2026-08-30_all_2.md)、
総合スコア50/100）の全指摘（P1×3・P2×5・P3×5）をユーザー承認により起票する。うちP1-1
（axis_definitions_snapshot.jsonの陳腐化）は、起票作業と並行して別セッションが
[T442](tasks/T442.md)として既に起票・完了させていたため重複起票しない。

- [x] [T443](tasks/T443.md) gradientの境界値がルート確定前の表示（評価軸ライン・環境グループ塗り）に未配線〔P1〕 規模S
- [x] [T444](tasks/T444.md) 風・勾配のfeature-stateクリアが共有され、同時ON時に片方OFFで両方消える〔P1〕 規模S〜M
- [x] [T445](tasks/T445.md) WindWayService/GradientWayServiceのbearing_deg型シグネチャがルーター層とOptional不一致〔P2〕 規模S
- [x] [T446](tasks/T446.md) buildRoadSurfaceSharedLayerIdsがgradientAxisを含まない非対称＋古いコメントの訂正〔P2〕 規模S
- [x] [T447](tasks/T447.md) secondaryAxes.tsのコメントがwindのcategory/show_map_icon除外機構を逆に説明している〔P2〕 規模S
- [x] [T448](tasks/T448.md) T427.mdのFinding 1が結果的に解消済みなのに未更新のまま半陳腐化〔P2〕 規模S
- [x] [T449](tasks/T449.md) architecture.mdが軸スタジオのshape kind数について自己矛盾している〔P2〕 規模S
- [x] [T450](tasks/T450.md) needs_bearing=False分岐が未テストのまま宣言されている〔P3〕 規模S
- [x] [T451](tasks/T451.md) MapView.tsxにT432で削除済みの関数を参照する古いコメントが残る〔P3〕 規模S
- [x] [T452](tasks/T452.md) gradientFillの独自実装統一DEFERにトリガー条件が明記されていない〔P3〕 規模S
- [x] [T453](tasks/T453.md) history/scores.mdのuiセクション、同日2行の「前回差分」列書式が不統一〔P3〕 規模S
- [x] [T454](tasks/T454.md) task/README.mdのディレクトリ図が_history.mdに触れておらずreview/README.mdと非対称〔P3〕 規模S

## 本番インシデント対応（2026-08-30・ルート生成候補0件の原因調査から）

- [x] [T441](tasks/T441.md) ルート候補0件の原因をGUI（デバッグログ）まで届ける+debugLogの重大度監査 規模M
- [x] [T442](tasks/T442.md) axis_definitions_snapshot.jsonがT440の軸変更に追従しておらず、fresh bootstrapと乖離している 規模S

## 統合レビュー第2回のシャーディング不具合修正後の再実施（2026-08-31、ユーザー承認済み）

統合レビュー第2回（`history/2026-08-30_all_2.md`）は、対象規模が大きくシャーディング要と
判定した際、4レンズ構造（overall/complexity/consistency/ui）をドメイン構造
（backend/frontend/Map/frontend其他/docs/ui）へ誤って置き換えてしまい、complexityレンズ
固有の出力（規模ウォッチ表・変更コスト表・Keep List照合）が丸ごと欠落していた（ユーザー
指摘により発覚）。レビュー基盤（principles.md/complexity.md/all.md）を修正した上で、
正しい設計（単独Agent・ドメイン分割なし）でcomplexity・overall（局所最適の連鎖検出）を
再実施した（[history/2026-08-31_complexity.md](../.claude/commands/review/history/2026-08-31_complexity.md)
スコア96/100、[history/2026-08-31_overall.md](../.claude/commands/review/history/2026-08-31_overall.md)
スコア90/100）。新規P1×1・P3×1を起票し、既存[T425](tasks/T425.md)・[T444](tasks/T444.md)・
[T428](tasks/T428.md)へ追記した（起票不要な情報のため新規タスク化せず）。

- [x] [T455](tasks/T455.md) T423・T440・T442が更新した軸定義フィールドの本番DB反映が実装記録から確認できない〔P1〕 規模S〜M
- [x] [T456](tasks/T456.md) AxisComposer.tsxのKeep List閾値文言「5つ目のshape種到達」がT396/T397後のモデルと不整合〔P3〕 規模S
- [x] [T457](tasks/T457.md) T425項目3・4と同じバグ（風のredraw未再適用・interactiveLayerIds除外漏れ）がgradientにも複製されている〔P2〕 規模S

## モジュール別設計書作成中の発見（2026-08-31、実コード確認のみで作成、発見即起票）

- [x] [T458](tasks/T458.md) DYNAMIC_WAY_VALUE_MATERIALSが軸スタジオのdedicated_way_value_layerと独立したハードコード辞書になっている 規模M
- [x] [T459](tasks/T459.md) car_stress_display_level()がAXIS_DEFINITIONS["car_stress"]を直接ハードコードしている 規模S〜M
- [x] [T460](tasks/T460.md) get_dynamic_way_value_serviceのサービス組み立てがmaterial_idのハードコードif/else分岐になっている 規模S
- [x] [T461](tasks/T461.md) GRADIENT_FILL_LAYER_IDにWIND_PENALTY_FILL_LAYER_IDと同型のクリックガードが無い 規模S

## openrouteserviceエンジンの完全削除（2026-08-31・ユーザー指示）

- [x] [T462](tasks/T462.md) openrouteserviceエンジンを完全削除しroad_graphへ一本化する 規模L

## 統合レビュー第3回の起票（2026-08-31、review:all、ユーザー承認済み「全件起票して」）

T440〜T471（69コミット）を対象とした3回目の統合レビュー
（[history/2026-08-31_all.md](../.claude/commands/review/history/2026-08-31_all.md)、
総合スコア29/100）の全指摘（P1×2・P2×5[まとめ含む]・P3×2[まとめ含む]・DEFER×2）を
ユーザー承認により起票する。

- [x] [T472](tasks/T472.md) jma_amedas_service.pyのRedis呼び出しをfail-open契約へ統一〔P1〕 規模S
- [x] [T473](tasks/T473.md) windBoundaries/gradientBoundariesの軸専用propを汎用機構へ統合し環境グループの配線漏れを解消〔P1〕 規模S〜M
- [x] [T474](tasks/T474.md) モジュール設計書・architecture.md・タスクファイルのドキュメントドリフト一括修正（10箇所）〔P2〕 規模M
- [x] [T475](tasks/T475.md) 軸スタジオAPI経由のDB変更に「本番DB反映」を完了条件として明記するCLAUDE.md追記提案〔P2〕 規模S
- [x] [T476](tasks/T476.md) MapOverlayControls.test.tsxへWidthSwatch統合・ref安定化の回帰テストを追加〔P2〕 規模S〜M
- [x] [T477](tasks/T477.md) T463/T464のタスク番号取り違えを実装コメント・テストコメントで一括訂正〔P2〕 規模S
- [x] [T478](tasks/T478.md) 統合レビュー第3回P3級指摘の一括対応（死コード削除・docs/テストの軽微是正10件）〔P3〕 規模M
- [ ] [T479](tasks/T479.md) region_service.py/graph_service.pyのクールダウン付きバックグラウンドトリガー共通化〔DEFER〕 規模S — トリガー: 3箇所目発生時
- [ ] [T480](tasks/T480.md) 動的材料のクリックガード（`GRADIENT_FILL_LAYER_ID`等）の汎用化〔DEFER〕 規模S — トリガー: 3件目の動的材料追加時
- [x] [T481](tasks/T481.md) debugStatsApi.tsの手書き型をbackend側Pydanticモデル化してOpenAPI生成物経由へ統一する〔P3〕 規模S〜M

## CI調査（2026-08-31）

- [x] [T482](tasks/T482.md) GitHub Actions CIの`e2e`ジョブが直近複数コミット連続で失敗している原因を調査する 規模S〜M
- [x] [T483](tasks/T483.md) windPenalty.tsの物理式JS移植とwindAxisPenalties/gradientAxisValuesの軸別prop構造の要否検討 規模S〜M

## ユーザー報告バグ修正（2026-08-31）

- [x] [T484](tasks/T484.md) 動的気象レイヤーのfilter未設定時にMapLibre style検証エラーが起動時毎回出る不具合を修正 規模S
- [x] [T485](tasks/T485.md) ルート線クリック時のレーダーチャートポップアップが常にエラーで表示されない不具合を修正 規模S
- [x] [T486](tasks/T486.md) ルート設定・ルート結果パネルの省スペース化と色分けの2択簡素化 規模L
- [x] [T487](tasks/T487.md) ルート設定パネルの軸1行あたりの高さをモバイルで半減させる 規模S
- [x] [T494](tasks/T494.md) 洪水キキクル(vectorTile)のタイルURL相対パス起因のクラッシュ「地図が出なくなった」を修正 規模S

## プロジェクト規模監査（2026-08-31、ユーザー依頼）

- [x] [T488](tasks/T488.md) JMA系等シンプル外部APIクライアントの「TTLCache参照＋fetch＋エラー処理」定型文を共通ヘルパーへ抽出 規模S

## モバイルUI実機フィードバック対応（2026-08-31、ユーザー報告）

- [x] [T489](tasks/T489.md) ルート設定パネル（モバイル）のスライダー整列・ネストスクロール・部品サイズを是正 規模S
- [x] [T492](tasks/T492.md) 風・勾配の走行方位コンパスをルート設定パネルへ移設（BottomSheet展開中に隠れる問題の解消） 規模S
- [x] [T493](tasks/T493.md) ルート設定パネルの重み配分をポップオーバー方式へ再設計、除外道路の並び順修正 規模S
- [x] [T495](tasks/T495.md) 重み配分バー（帯グラフ）をドラッグ可能にし直感的な配分UIにする 規模S
- [x] [T496](tasks/T496.md) 重み配分バーの帯色が軸数超過時に衝突していたのを修正 規模S
- [x] [T497](tasks/T497.md) ルート設定パネルの軸行をチェックボックス+スライダーから凡例チップへ再設計 規模M
- [x] [T498](tasks/T498.md) 重み配分バーへ凡例ポップオーバー・ドラッグ中のライブ%表示を追加 規模S
- [x] [T499](tasks/T499.md) 地図上の色分け凡例を追加（勾配・風・ramp軸） 規模M
- [x] [T500](tasks/T500.md) 走行方位コンパスのタッチ判定をリング全周へ拡大 規模S
- [x] [T502](tasks/T502.md) 地図色分け凡例がモバイルのBottomSheetに隠れる問題を修正 規模S
- [x] [T503](tasks/T503.md) 走行方位コンパスを円環ドラッグから矢印回転式へ作り替え 規模M
- [x] [T504](tasks/T504.md) 走行方位（風・勾配）の設定を単一の共有値・単一の入口へ統合 規模M
- [x] [T506](tasks/T506.md) 走行方位アイコンを現在値を映すミニダイヤルへ再設計 規模S
- [x] [T507](tasks/T507.md) 走行方位アイコンをMapLibreのズーム+/−コントロールと同じ見た目へ統一 規模S
- [x] [T508](tasks/T508.md) 走行方位アイコンの左右位置をMapLibreコントロールへぴったり揃える 規模S

## テスト有効性・カバレッジ監査の起票（2026-08-31、ユーザー依頼、ユーザー承認済み）

- [x] [T490](tasks/T490.md) MapView.tsxの並列トラック分離・二次軸下敷き・setStyle後再適用ガードをexportして単体テスト化する 規模M
- [x] [T491](tasks/T491.md) backend main.pyのlifespan（起動・終了シーケンス）を検証するテストを追加する 規模S〜M

## 記載外の改善（2026-08-31、ユーザー依頼）

- [x] [T501](tasks/T501.md) 軸スタジオの複製しきい値リセット・公開済み軸の表示専用フィールド直接編集 規模M
- [x] [T505](tasks/T505.md) モバイルUI全体の省スペース化（ボタン・余白の統一的な圧縮） 規模L
- [x] [T509](tasks/T509.md) 標高図をサイドバー「地図の見え方」パネルから除外（地図上チップのON/OFFは維持） 規模S
- [x] [T511](tasks/T511.md) 風・勾配のcos向き投影式（wind_penalty/effective_gradient）の共通化〔DEFER〕 規模S
- [x] [T512](tasks/T512.md) 風の評価軸凡例に体感ラベル（強い向かい風/軽い追い風等）を追加 規模S
- [x] [T513](tasks/T513.md) 評価軸の凡例ラベルを軸スタジオ設定可能な汎用フィールド化（T512のハードコード是正） 規模M
- [x] [T510](tasks/T510.md) JMA動的タイルの429対策（レート制限順序修正＋Redisキャッシュ＋定期プリウォーム） 規模M〜L

## T510プリウォームの本番投入後に判明した負荷対応（2026-08-31）

- [x] [T514](tasks/T514.md) JMAタイルプリウォームへの自前レート制御追加 規模S〜M

## 風の環境グループgridFill、粗格子/詳細格子の二重塗り解消（2026-08-31）

- [x] [T515](tasks/T515.md) 粗格子/詳細格子の重なりを幾何学的に切り取って二重塗りを解消 規模M

## 洪水キキクルタイル未リクエスト報告の調査（2026-09-01・ユーザー報告）

- [x] [T516](tasks/T516.md) 洪水キキクル(flood)タイル未リクエスト報告の調査 規模S

## 「開発者」タブからバックエンドの直近ログを見られるようにする（2026-09-01・ユーザー指摘）

- [x] [T517](tasks/T517.md) 開発者タブへバックエンドログ表示パネルを追加 規模M
- [x] [T518](tasks/T518.md) ルート結果パネルの再構成（「ルート選択」への統合＋重み反映＋表示トグル修正） 規模M〜L

## nowcグループの未使用element調査（2026-09-01、雷・竜巻basetime調査の副産物）

- [x] [T520](tasks/T520.md) nowcグループ（targetTimes_N3.json）の未使用element調査（liden・slmcs系） 規模不明
- [x] [T541](tasks/T541.md) liden（雷放電位置データ）の地図表示を実装する 規模M
- [ ] [T542](tasks/T542.md) slmcs系（線状降水帯直前検出・予測領域）の地図表示を実装する 規模S〜M — トリガー: 実際の線状降水帯発生時にgeometry構造を実機確認できた時点

## 雷・竜巻ナウキャストのbasetime選択バグ修正（2026-09-01、T514効果確認の副産物）

- [x] [T521](tasks/T521.md) 雷・竜巻ナウキャストのbasetime選択バグ修正（liden-onlyエントリを誤って採用） 規模S

## ルート生成が異常に遅くなる事象の調査（2026-09-01、T518実機確認中の副産物）

- [x] [T522](tasks/T522.md) ルート生成が異常に遅くなる事象の調査（prepare段階＝探索用グラフ構築が支配的、backendログで特定） 規模不明
- [x] [T523](tasks/T523.md) ルート生成のフロントポーリングが「signal timed out」で失敗する事象の調査 規模不明
- [x] [T529](tasks/T529.md) ルート生成の探索コスト計算をlazy評価化（rustworkx+A\*）してprepare_msを根本的に短縮 規模L
- [x] [T530](tasks/T530.md) wind/nightを汎用的な動的コンテキストへ統合するリネーム・再設計 規模S〜M
- [x] [T531](tasks/T531.md) 公開軸重み駆動のフロンティア方式による周回ルート生成（一対全Dijkstra木から折返し点を選定→retraceペナルティ付き復路探索、候補数max_routes指定可能化） 規模L
- [x] [T532](tasks/T532.md) 探索中の風評価を時変化（時刻依存の到達時刻ベース再評価）に対応する 規模M
- [x] [T585](tasks/T585.md) `round1_array`（Python `round()`の要素ループ）をビット一致のままベクトル化しprepareの固定費（本番25kmでcost_ms約1.8秒）を削る 規模S
- [x] [T536](tasks/T536.md) 探索コストを「タイル単位の静的スコア行列＋リクエスト時ベクトル計算」へ変え、A*からPythonコールバックを外す 規模L
- [x] [T537](tasks/T537.md) 探索用グラフ・索引をタイル集合キーでキャッシュする（prepare温パス2.4秒→0.4秒程度） 規模M
- [x] [T538](tasks/T538.md) タイル材料キャッシュの冷パス（デプロイごとに29秒）を永続化または起動時予熱で解消する 規模M
- [x] [T539](tasks/T539.md) 交差点分割（split）をPBF取込後のバッチで全域に済ませ実行時再構築を無くす 規模M
- [x] [T540](tasks/T540.md) 周回探索で距離許容超過が確定した時点でレグ3を探索しない早期打ち切り 規模S
- [x] [T546](tasks/T546.md) タイル材料キャッシュを列指向表現へ変え、デプロイ直後の復元を5秒未満にする（T538再検討案C1） 規模M

## 過去の経緯由来の冗長な分割・マージ漏れの総点検（2026-09-01、T522派生の辞書統合作業中のユーザー提案）

- [x] [T533](tasks/T533.md) 過去の経緯だけで保持している冗長な分割・マージ漏れの総点検 規模不明
- [x] [T543](tasks/T543.md) T533で見つかった評価パイプラインの旧設計残骸を解消する 規模S〜M

## 軸別スコアの事前計算キャッシュ（2026-09-01、T522派生・compute_edge_cost内部調査の続き）

- [x] [T534](tasks/T534.md) 軸別スコアの事前計算キャッシュ（compute_edge_cost内部の速度改善） 規模L

## T518コードレビュー指摘の対応（2026-09-01、/code-review実施の副産物）

- [x] [T524](tasks/T524.md) T518コードレビュー指摘の対応（全17件） 規模M
- [x] [T525](tasks/T525.md) 凡例UI（ポップオーバー・チェックボックス行）の共通化 規模M
- [ ] [T526](tasks/T526.md) 内訳バーの視覚表現見直し（軸数に応じて理論上100/N%まで潰れる） 規模S〜M — トリガー: 実機で「短すぎて比較しづらい」という実感が出た場合
- [x] [T527](tasks/T527.md) axis_difficulties型キャスト・useAxisCatalog複数インスタンスの型安全性調査 規模S〜M
- [x] [T528](tasks/T528.md) 未使用依存@radix-ui/react-radio-groupの削除 規模S

## 「ルートをクリア」しても地図に緑の線が残る事象の調査・修正（2026-09-02、ユーザー報告）

- [x] [T535](tasks/T535.md) 「ルートをクリア」で実験スロット（地図に残る緑線）も消えるようにする 規模S

## 重み配分バーのドラッグ中バッジの分かりにくさ（2026-09-02、ユーザー報告）

- [x] [T544](tasks/T544.md) 重み配分バーのドラッグ中バッジに軸ラベルを併記する 規模S

## ルート結果パネルの再設計（2026-09-02、ユーザー実機フィードバック）

- [x] [T545](tasks/T545.md) ルート結果パネルの再設計（ルートごとのタブ化・説明文整理・切り替えUI統一） 規模M

## 数値入力の使いやすさ改善（2026-09-03、ユーザー指摘）

- [x] [T547](tasks/T547.md) 生成距離・軸スタジオの数値入力を改良し、軸スタジオで負数を入力できるようにする 規模M

## おすすめ度（total_score）システムの全面撤去（2026-09-03、ユーザー指摘・合意）

- [x] [T548](tasks/T548.md) おすすめ度（total_score）を全面撤去し候補タブ並び順をoverall_difficulty基準へ 規模M

## supports_route_coloringフラグの全面撤去（2026-09-03、ユーザー指摘・合意）

- [x] [T549](tasks/T549.md) supports_route_coloringフラグを撤去し全公開軸を自動的にルート地図色分け対象へ 規模M

## ルート結果・区間詳細の軸表示統一（2026-09-03、ユーザー指摘・合意）

- [x] [T550](tasks/T550.md) 重み付き寄与度のbackend算出化・区間詳細のボトムシート統合・タップ判定拡大 規模M

## 周回・目的地ルートの上位N件化（2026-09-03、T531推敲時のユーザー提案）

- [x] [T551](tasks/T551.md) 目的地ルートを上位N件（via-node方式の代替経路）へ拡張する 規模M
- [x] [T552](tasks/T552.md) 重み付き軸がすべてデータ欠損のEdgeのコストを「最良扱い」から「bbox平均difficultyで補完」へ 規模S〜M
- [x] [T553](tasks/T553.md) フロンティア方式の候補間で「同じ周回の逆回り」を重複として棄却する（周回単位の重複率チェック） 規模S
- [x] [T554](tasks/T554.md) フロンティア方式の折返し点選定で同点時に方位の広がりを優先するタイブレーク 規模S

## T531後のbackend残存コメント・デッドコードのクリーンアップ（2026-09-03、T531 docs同期作業の副産物）

- [x] [T555](tasks/T555.md) T531後に残った8方位gather前提の古いコメント（`get_edges_with_geometry`のロック根拠等）と本番未参照になった`destination_point`のクリーンアップ 規模S
- [x] [T556](tasks/T556.md) 本番のsplit済み範囲を周回生成の新bbox（目標距離の0.4倍＋マージン）に合わせて拡大する 規模S〜M
- [x] [T557](tasks/T557.md) T531（フロンティア方式）の`/code-review`指摘の是正（上位10件＋P3相当10件） 規模M
- [x] [T568](tasks/T568.md) SearchGraphStatics/選定間引きのメモリ最適化（entry_keys撤去・int32化・ビットマスク化） 規模M
- [x] [T586](tasks/T586.md) 周回の折返し点選定（`select_loop_turnarounds`）の木の後段処理が本番で約3.3秒かかる遅延の調査・是正（T531実測時のselect_ms 141ms→3,390ms、木自体は約110ms） 規模S〜M
- [x] [T569](tasks/T569.md) preview_segmentがSearchGraphStaticsを不要に構築・キャッシュしている問題の分離 規模S〜M

## 周回ルートの進行方向矢印が見えない問題（2026-09-03、ユーザー報告）

- [x] [T558](tasks/T558.md) 進行方向矢印（T293）が区間色分け線の下・同色で沈んで見えない問題の修正（重ね順の明示＋縁取り層の配置保証） 規模S
- [x] [T559](tasks/T559.md) 風の矢印（動的気象レイヤーwindVector）の縁取り層が1つも配置されない問題の修正（T558と同構造） 規模S
- [x] [T560](tasks/T560.md) 周期レビュー（`/review:all`）の負荷軽減——トリガーを「14日 or 実装変更20,000行」へ見直し、死んだ参照・記載漏れ・状態行照合・規模ウォッチ・メトリクスを`scripts/review_checks.py`へ機械化、overall/consistencyのシャード共有 規模M

## 統合レビュー第4回（2026-09-03）の指摘対応と、review_checks.py初回監査の既存乖離の是正（2026-09-03、ユーザー承認）

- [x] [T561](tasks/T561.md) docs/modules記載粒度違反の再発22箇所（`routing-engine.md`16・`evaluation-scoring.md`6）の是正と、経緯記述の機械検知パターン拡充（`改善計画T[0-9]+で`以外の言い回し）・フックとスクリプトのパターン二重管理の解消 規模M
- [x] [T562](tasks/T562.md) `docs/architecture.md`のbackendディレクトリツリーへT536〜T539/T546新設4ファイル（`search_graph_cache.py`・`tile_persistent_cache.py`・`tile_score_matrix_cache.py`・`presplit_road_graph.py`）を反映 規模S
- [x] [T563](tasks/T563.md) docsドリフトの一括是正（`map-axis-coloring.md`・`MapColorLegend.tsx`コメント・`axisLayers.ts`死んだ参照・`docs/logging.md`例外規定・`developer-research-tools.md`へdebug/logs/route.ts）と、docs/tasks「状態:」行の整備（T501/T505の完了反映、「状態:」行なし17件の追加） 規模M
- [x] [T564](tasks/T564.md) docs/modulesに一切出現しない既存実装ファイル18件（汎用UI部品9・機能部品5・admin API routes4）の扱いを決めて記載し、`scripts/review_checks.py docs`をCIワークフローへ組み込む 規模M

## ルート直下README.mdの陳腐化是正（2026-09-03・ユーザー指摘）

- [x] [T565](tasks/T565.md) ルート直下README.mdの陳腐化是正 規模M

## ソースコード内の経緯コメント氾濫対応（2026-09-03・ユーザー指摘）

- [x] [T566](tasks/T566.md) ソースコード内の経緯コメント氾濫の恒久防止ルール化 規模S
- [x] [T567](tasks/T567.md) 既存ソースコードの経緯コメント一掃（モジュール単位で分割） 規模XL
- [x] [T570](tasks/T570.md) コメント方針（T566）の機械的強制 規模M
- [x] [T622](tasks/T622.md) 経緯コメント機械スキャナ（review_checks.py）のカバレッジ穴を塞ぐ 規模S

## T281段階3の独立起票（2026-09-04・派生データ再構築の単一エントリポイント実装に伴う分離）

- [x] [T571](tasks/T571.md) 派生データ鮮度台帳（生データ更新時刻 vs 派生computed_atの機械比較、T281段階3） 規模M

## 過去[x]タスクに埋もれていた未起票残項目の監査・分離（2026-09-04・ユーザー指摘）

- [x] [T572](tasks/T572.md) 国土地理院 色別標高図タイルのバックエンド永続キャッシュ化 規模S

## 本番DB再構築（disaster recovery）手順の整備（2026-09-04・ユーザー指示）

- [x] [T573](tasks/T573.md) 本番DB再構築（disaster recovery）の包括的手順書整備・検証 規模L
- [x] [T574](tasks/T574.md) refresh_derived.py実行後にタイル永続キャッシュ版数が上がらず本番へ反映されない 規模S
- [x] [T575](tasks/T575.md) `_tile_grid_cache`（DEMタイル解析済みグリッド）にサイズ上限が無くOOMを起こす 規模S
- [x] [T576](tasks/T576.md) precompute_elevation_attributesの高速化（地理的順序＋タイル単位バッチ化） 規模M
- [x] [T577](tasks/T577.md) 材料ごとの欠損割合を管理画面で可視化する 規模M

## 路面タイル配信の高速化（2026-09-04・T577フォローアップの調査結果）

- [x] [T578](tasks/T578.md) 路面タイル配信の高速化（指定路線JOINのLATERAL化・応答のgzip圧縮） 規模S〜M
- [x] [T579](tasks/T579.md) test_wind_way_serviceの時刻依存フレーク（23時台に必ず失敗する） 規模S
- [x] [T580](tasks/T580.md) 路面タイルをRenderフロントを経由せずbackendへ直接配信する（接続上限対策とセット） 規模M
- [x] [T581](tasks/T581.md) 基礎地図・国土地理院・JMAタイルもbackend直接配信へ（T580の適用範囲拡大） 規模M
- [ ] [T582](tasks/T582.md) 本番VMのネットワーク許可ルールを設計どおりに是正する（SSH 22番の全開放・iptablesの5432無制限行） 規模S — トリガー: 本格公開の意思決定
- [x] [T583](tasks/T583.md) 管理画面「材料」タブの表示を簡素化し他タブと統一する 規模S
- [x] [T584](tasks/T584.md) 材料`no_lit`（街灯なし）を`lit`（街灯あり）へ正規化し、専用の反転機構を撤去する 規模M

## MapLibreレイヤーのensure関数が既存レイヤーの色式を更新しない不具合（2026-09-05・ユーザー報告の風penalty面塗り色異常の調査から発覚）

- [x] [T587](tasks/T587.md) MapLibreレイヤーのensure関数（windAxis/gradientAxis/gradientFill・ramp軸全般）が既存レイヤーの色式（軸スタジオのdisplay_thresholds_override等）を更新しない 規模M

## 既存テストの不安定化（2026-09-05・T532最終検証の副産物、ユーザー指示で起票）

- [x] [T588](tasks/T588.md) `test_lifespan_registers_jma_tile_prewarm_job_with_immediate_next_run_time`がフルスイート/ファイル単位でのみ失敗する（単体では成功、masterでも再現）時間依存の不安定化を調査・是正する 規模S

## 迂回率の実測値化（2026-09-05・T532本番実測を受けたユーザー判断）

- [x] [T589](tasks/T589.md) 迂回率（道なり距離÷直線距離）を定数1.3から実測値へ——復路は往路木の実測中央値、往路は探索範囲（タイル集合）ごとにプロセス内で学習した値を使う 規模S

## 風penaltyの二乗則化とレンズUI再編（2026-09-05・ユーザー検討依頼から合意、T590を分割元とする一連）

- [x] [T590](tasks/T590.md) 風penaltyの二乗則化とレンズUI再編（分割元・設計メモ） 規模L
- [x] [T591](tasks/T591.md) 二乗則の風材料を追加しバックエンドの3経路へ走行速度を配線する 規模M
- [x] [T592](tasks/T592.md) 区間・候補の物理量表示を材料カタログ駆動へ汎用化する 規模M
- [x] [T593](tasks/T593.md) 専用way値レイヤーの配信値を難易度スケールへ統一しdisplay_thresholds_overrideの二重帰属を解消する 規模M
- [x] [T594](tasks/T594.md) 動的way値配信へ走行速度を伝播する（dynamic_way_value_needs_speed） 規模S
- [x] [T595](tasks/T595.md) 地図の色分け（レンズ）の入口を1箇所へ統合し重み0の軸も選べるようにする 規模M
- [x] [T596](tasks/T596.md) 出発時刻・走行方位・想定速度を地図下辺の条件バー1本へ集約する 規模M
- [x] [T597](tasks/T597.md) デスクトップのサイドバーをモバイルと同じ3区分にし、ルート結果ヘッダに保存・GPX出力の操作枠を確保する 規模S
- [x] [T598](tasks/T598.md) 軸スタジオの折れ点編集を参考点・自動生成・効き目プレビューで省力化する 規模M
- [x] [T599](tasks/T599.md) 本番の風軸を新材料へ切り替えbreakpoints・override・段階ラベルを較正しスナップショットを更新する 規模S
- [x] [T600](tasks/T600.md) 軸スタジオの曲線エディタに実データ分布（分位点）を重ね描きする 規模M

## 直近UI改修（T595〜T597）の完了条件乖離是正（2026-09-05・ユーザー指摘の総点検から）

- [x] [T601](tasks/T601.md) T595〜T597の完了条件乖離是正（出発時刻ドラッグタイムライン化・デッドコード/ドキュメント整合） 規模M

## 目的地ルート生成のアクセス不能地点への孤立スナップ是正（2026-09-05・ユーザー報告「目的地検討が動かなくなった」の調査から）

- [x] [T602](tasks/T602.md) 目的地ルート生成が起点に一番近いNodeへスナップした結果アクセス不能になる不具合の是正と、アクセス可能な最寄りNodeへの自動補正 規模M

## JMAタイルプロキシの404を502/WARNINGにしていた不具合の是正（2026-09-05・T602実機検証中のユーザー報告から）

- [x] [T603](tasks/T603.md) JMAタイルプロキシが「疎な格子で珍しくない404」を他の失敗と同じ502/WARNINGにしていた不具合の是正 規模S

## 「地図の一部が塗られない」ユーザー報告の調査（2026-09-05・降水延長予報gridFillの調査から）

- [x] [T604](tasks/T604.md) 降水延長予報gridFillの「未着色」が取得失敗によるものか閾値未満によるものか区別できない 規模S

## 恒久404（疎な格子・整備区域外）の未キャッシュ問題の横展開是正（2026-09-05・T603の設計指摘「疎な格子状タイルを受け取ったときどうあるべきか」から）

- [x] [T605](tasks/T605.md) JMAタイル・色別標高図タイルの確認済み404を未キャッシュのまま毎回上流へ問い合わせていた問題の是正 規模S

## キキクル4種・風/勾配road-value系レイヤーのデータ取得状態（読込中/データなし/失敗）可視化（2026-09-05・ユーザー指摘「風とかも今は読込待ちなのか区別がつかない」から）

- [x] [T606](tasks/T606.md) キキクル4種を地図上チップ化しdataStatusドット機構をMapOverlayControlsへ拡張 規模M
- [x] [T607](tasks/T607.md) 風/勾配road-value系レイヤーのデータ取得状態（読込中/データなし）可視化 規模S

## 動的気象レイヤーのデータ取得状態をMapLibreソースイベント非依存の統一IFへ再設計（2026-09-05・T606/T607完了後のユーザー監査依頼「読込中/データなしを区別できないレイヤーが他にも残っていないか」から）

- [x] [T608](tasks/T608.md) 動的気象レイヤーのデータ取得状態をMapLibreソースイベント非依存の統一IFへ再設計 規模M

## 出発時刻ポップオーバーの透過バグ再発とUI簡素化（2026-09-05・ユーザー報告「まだボタンが透けて消える」「クリック後に透過している」から）

- [x] [T609](tasks/T609.md) 出発時刻ポップオーバーの透過バグ修正とドラッグタイムラインの直接日時指定UIへの置き換え 規模S

## 災害系レイヤーの1チップ統合（2026-09-06・ユーザー要望「災害系のパネルを1つにまとめたい」から）

- [x] [T610](tasks/T610.md) 災害系レイヤー7種（雷・竜巻・落雷・土砂・大雨・浸水・洪水）を1つの「災害」チップへ統合する 規模M
- [x] [T612](tasks/T612.md) 地図上チップの▶パネルを表示専用から操作可能へ（全チップ共通の内訳トグル） 規模S
- [x] [T615](tasks/T615.md) 地図上チップの排他ドメインを廃止し、すべて複数選択可にする＋▶パネルへ一括ON/OFFを追加 規模M

## T609の過剰実装是正（2026-09-06・ユーザー指摘「スライダーバーまですべて消えている」から）

- [x] [T611](tasks/T611.md) T609で誤って削除したドラッグタイムライン（DynamicLayerTimeSlider）を復元し、直接日時指定はその追加手段として両立させる 規模S

## T597完了条件の未達是正（2026-09-06・ユーザー指摘「周回/目的地選択はルート設定パネルにまとめる話だったはず」の点検から）

- [x] [T613](tasks/T613.md) モバイルの「ルート設定」タブに周回/目的地選択（RouteForm）が入っておらず常時表示バーに取り残されている問題を是正する 規模S

## 「ルート設定」パネルの高さ圧縮（2026-09-06・ユーザー指摘「もう少し高さ低くて収まるようにしたい」から）

- [x] [T614](tasks/T614.md) 「ルート設定」パネルをタブ分割・入力欄圧縮・説明文のinfoアイコン化で高さを圧縮する 規模M
- [x] [T616](tasks/T616.md) 「ルート設定」の実機調整（生成ボタンをタイトル行へ・距離スライダー化/候補数簡易選択化・目的地モード自動武装） 規模M

## 「ルート結果」の実機調整（2026-09-06・ユーザー報告「ルートをクリアもアイコン化」「区間クリックすると落ちる」「棒グラフの必要性確認」から）

- [x] [T617](tasks/T617.md) 「ルート結果」の実機調整（ルートをクリアのアイコン化・区間クリックのクラッシュ修正・AxisContributionBarの未使用軸表示バグ修正） 規模M

## ルート候補の距離評価（2026-09-06・ユーザー指摘「難所があっても距離が長く遠回りした方が常に最適判断されてユーザの判断余地がない」から）

- [x] [T618](tasks/T618.md) 候補選定をパレート非劣解へ再設計し、難易度の総量を併記する 規模M

## レンズ（地図色分け）の風表示バグ（2026-09-06・ユーザー報告「レンズで風を選ぶと全灰色」から）

- [x] [T619](tasks/T619.md) レンズで風を選ぶと全灰色になるバグを修正 規模S
- [x] [T620](tasks/T620.md) 風・勾配（dedicated_way_value_layer軸）のフェッチ失敗を既存の失敗バナーへ表示する 規模M
- [x] [T623](tasks/T623.md) 風の評価軸を既存の細かい風グリッドへ乗せ替える 規模S
- [x] [T624](tasks/T624.md) 開放度（遮蔽物）推定軸の新設 規模M/L

## 走行条件バーの配置（2026-09-06・ユーザー指摘「下部パネルを開いていると隠れて使いにくい」から）

- [x] [T625](tasks/T625.md) 走行条件バーをレンズピル直下（地図上部中央）へ移設 規模S

## GPX出力機能（2026-09-06・ユーザー要望「GPX出力機能は追加できる？」から）

- [x] [T626](tasks/T626.md) GPX出力機能の実装 規模S
- [x] [T786](tasks/T786.md) GPX出力の間引きで細かい曲がりが消える 規模S

## 「ルート結果」情報アイコンの位置（2026-09-06・ユーザー指摘「タイトルの説明は総合難易度の説明。パネル内の総合難易度のところに移動して」から）

- [x] [T627](tasks/T627.md) 「ルート結果」の情報アイコンを総合難易度の隣へ移設 規模S

## ボタン系スタイルの統一（2026-09-06・ユーザー指摘「ルート生成パネルとルート結果パネルで、ボタンの色味とか不統一感がある」から）

- [x] [T628](tasks/T628.md) 「ルート設定」「ルート結果」パネルのボタン系スタイルを統一する 規模M

- [ ] [T629](tasks/T629.md) ボタン系CSSの共有コンポーネント化（「地図の見え方」パネル再編と合わせて） 規模L — トリガー: 「地図の見え方」パネル[MapLayersPanel]の再編に着手するとき

## キキクルの拡大時の色消失・描画速度の調査（2026-09-06・ユーザー報告「キキクルで拡大すると色が消える」「そもそも描画が遅い」から）

- [x] [T630](tasks/T630.md) キキクルで拡大すると色が消える・描画が遅い 規模M

## 目的地の名前検索（2026-09-06・ユーザー相談「ルート設定タブで、目的地を名前から検索して設定したい」から）

- [ ] [T631](tasks/T631.md) 目的地の名前検索（ジオコーディング）機能の追加 規模L

## 候補ルートの区間単位の組み合わせ（2026-09-06・ユーザー指摘「各セクションのいいとこ取りをしたいのに」から）

- [x] [T621](tasks/T621.md) 候補ルートを分岐点で乗り換えられるようにする（区間のいいとこ取り） 規模L
- [x] [T763](tasks/T763.md) 候補の後処理チェーンを1箇所へ寄せる 規模S

## 天候・災害レイヤーの表示高速化（2026-09-07・ユーザー指摘「天候系、災害系のレイヤは、表示するのに非常に時間がかかる」から）

- [x] [T632](tasks/T632.md) 応答のHTTPキャッシュヘッダを一元管理する仕組みと全エンドポイントへの適用 規模M
- [x] [T633](tasks/T633.md) キキクルがz11以上で消える（配信元が奇数ズームに実データを持たない） 規模S〜M
- [x] [T634](tasks/T634.md) targetTimes*.jsonの取得をタイルと同じ直接配信オリジンへ揃える 規模S
- [x] [T635](tasks/T635.md) タイル在否インデックスを全タイル系エンドポイント共通の仕組みとして設ける 規模L
- [ ] [T636](tasks/T636.md) JMAタイルのRedisキャッシュからbase64+JSONの包装を外す 規模S — トリガー: T632・T633の効果を実測してもなおbackendのCPUが問題になる場合
- [x] [T637](tasks/T637.md) 洪水（ベクタ）とキキクル（ラスタ）の更新タイミングのずれを調査する 規模S

## 開発機のテスト環境（2026-09-07・T632の全体テスト実行中に発覚）

- [x] [T638](tasks/T638.md) 開発機でPostgreSQL同梱のPROJとrasterioのPROJが衝突しテストが失敗する 規模S

- [x] [T964](tasks/T964.md) PostGIS統合テストが、並行セッション間で同じDBを共有している 規模S

## 「地図データを再読み込み」の責務分離（2026-09-07・ユーザー指摘「サーバ側の操作と、ブサウザ側の操作が1アクション内で混ざってしまっていて望ましくない設計。分離すべき」から）

- [x] [T639](tasks/T639.md) 「地図データを再読み込み」ボタンのサーバー側操作とブラウザ側操作を分離し、サーバー側を管理画面へ移す 規模M

## 点データタイル配信の汎用化（2026-09-07・ユーザー相談「事故とPOIも統合するとメリット大きそう」から）

- [ ] [T640](tasks/T640.md) 点データタイルの配信をレイヤー名パラメータで1実装へ汎用化する 規模M — トリガー: 次に点レイヤーを追加する必要が生じたとき

- [x] [T641](tasks/T641.md) 配信元が持たないズームのJMAタイルをサーバー側で補間する 規模M

- [x] [T642](tasks/T642.md) 雷ナウキャストの活動度1が画面を覆い、他の災害情報が埋もれる 規模S〜M

- [x] [T643](tasks/T643.md) 地域タイルの取得失敗が「200＋空タイル」で返り、1時間キャッシュされる 規模S〜M

## サーバー側キャッシュの保持方式（2026-09-07・ユーザー指摘「色々とパターンがありすぎてる気がする。精査するとより良い保持の仕方があるもの、考え方が統一されていないものもある」から）

- [x] [T651](tasks/T651.md) Redisを残すか撤去するかを実測で決める 規模M
- [x] [T652](tasks/T652.md) ルート生成からRedisを追い出す（2つのcache-asideを削除） 規模M
- [x] [T649](tasks/T649.md) ディスク永続キャッシュの世代滞留を止める 規模S〜M
- [x] [T647](tasks/T647.md) キャッシュ方針（docs/caching.md）の機械的な強制とCLAUDE.mdへの接続 規模S
- [x] [T653](tasks/T653.md) ディスク永続キャッシュを`diskcache`へ寄せる（自前実装の廃止） 規模M
- [x] [T644](tasks/T644.md) サーバー側キャッシュの保持方式を精査し、重複した骨格を共通化する 規模L→S

## 風・降水予報のMSM移行（2026-09-07・ユーザー相談「今は風予報はOpenMeteoで取っている。ただこれは外部APIを都度叩いているので429発生しやすい。MSM経由で取ることはできない？」から）

- [x] [T645](tasks/T645.md) 風・降水予報をOpen-Meteo REST APIから気象庁MSM（.om直読み）へ移行 規模L
- [x] [T646](tasks/T646.md) MSM配信が止まったことを検知する（同期バッチの鮮度WARNING） 規模S

## 写経の機械的検出（2026-09-07・ユーザー指摘「同じように、個別で同じような処理をいっぱい書いてるのって、見つけて正すことはできない？」から）

- [x] [T648](tasks/T648.md) 同種の処理が各所へ写経されるのを機械的に検出する 規模M

- [x] [T650](tasks/T650.md) コピペ検出で挙がった重複を個別に潰す 規模S〜M
- [x] [T771](tasks/T771.md) 既存の仕組みを作り直していないかを、実装前に機械で気づく 規模S〜M

- [x] [T766](tasks/T766.md) RouteCandidateのテストフィクスチャを1箇所へ寄せる 規模S

## 停止密度の作り直し（2026-09-08・ユーザー相談「ストップアンドゴーが少ない、風影響が少ないルートを作りたい。どんな軸を作ったらいい？」から）

- [x] [T654](tasks/T654.md) OSM取込対象（層0）へ自転車の停止要因を追加する 規模S
- [x] [T655](tasks/T655.md) 停止密度を作り直す（種別別カウント・way上カウント・信号のクラスタ化） 規模M〜L
- [x] [T719](tasks/T719.md) 停止密度の旧集計（stop_count）を撤去する 規模M
- [x] [T720](tasks/T720.md) 停止密度の飽和解消を本番で確認する 規模S
- [x] [T764](tasks/T764.md) 事故密度を「その道で起きた事故」で数え直す 規模M〜L
- [x] [T765](tasks/T765.md) 交差点カウントを「その道が通る交差点」で数え直す 規模S
- [x] [T787](tasks/T787.md) 停止1回のコストが実際の時間損失に対して過大 規模S〜M
- [x] [T753](tasks/T753.md) Way単位の材料解決が舗装タグを拾えていない 規模S
- [x] [T721](tasks/T721.md) ドメインモデルが未知フィールドを黙って捨てていないか点検する 規模S

## レビュー基盤・検知の空白（2026-09-08・統合レビュー第5回より）

- [x] [T656](tasks/T656.md) 経緯コメントの機械的検知の穴を塞ぐ（docstring・CSS・パターン） 規模S
- [x] [T657](tasks/T657.md) backendの列挙・既定値をexport_openapiの生成物へ集約する 規模M
- [x] [T658](tasks/T658.md) 規模ウォッチの次閾値を確定し、反映経路を一方向にする 規模S

## 統合レビュー第5回の指摘（2026-09-08）

[2026-09-08_all.md](../.claude/commands/review/history/2026-09-08_all.md) が検出した131件を、
起票単位で27本へ束ねたもの（12件はT656〜T658で対応済みのため除く）。**全131件が
いずれかのタスクへ割り当て済み**であることを機械的に検算してある。
各タスクの本文が対象の指摘を表で持つので、どれを実施しどれを見送るかはタスク内で判断する。

- [x] [T659](tasks/T659.md) 評価結果が誤る3件を直す（openness欠損値・逆回りレグ・AxisComposerの素通し） 規模M
- [x] [T660](tasks/T660.md) precompute系4本の全量ロードをサーバーサイドカーソルへ 規模M
- [x] [T661](tasks/T661.md) 認可・レート制限の非対称を是正する 規模S〜M
- [x] [T662](tasks/T662.md) 生成条件のdirty判定を単一ソースから導出する 規模M
- [x] [T663](tasks/T663.md) 軸スタジオのGUI操作で500になる構成を書き込み時に拒否する 規模S〜M
- [x] [T664](tasks/T664.md) 方位ラベルの丸め差（偶数丸め vs half-up）を解消する 規模S
- [x] [T665](tasks/T665.md) jma-tile-indexにPydanticレスポンスモデルを与える 規模S
- [x] [T666](tasks/T666.md) lazy_graphの整合ガードを実消費コレクションへ広げる 規模S
- [x] [T667](tasks/T667.md) localStorage読み出しの未保護をなくす 規模S
- [x] [T668](tasks/T668.md) docs/tasksの「状態:」行を統一し機械照合をすり抜けなくする 規模S
- [x] [T669](tasks/T669.md) architecture.mdの現状化（削除済みRedis機構ほか） 規模S〜M
- [x] [T670](tasks/T670.md) docs/modules 全15ファイルの現状化 規模M
- [x] [T671](tasks/T671.md) ソースコメントの参照先・個数表現・契約記述を是正する 規模S〜M
- [x] [T672](tasks/T672.md) dedicated_way_value_layer軸の汎用化を最後まで通す 規模M
- [x] [T673](tasks/T673.md) 材料追加の1本道を回復する 規模L
- [x] [T674](tasks/T674.md) カタログ・グループ列挙の導出漏れを塞ぐ 規模S
- [x] [T675](tasks/T675.md) 未定義CSSトークンを是正しトークン実在チェックを追加する 規模S
- [x] [T676](tasks/T676.md) UI/CSSの重複と不整合を解消する 規模M
- [x] [T677](tasks/T677.md) フロントの残骸を撤去する 規模S〜M
- [x] [T678](tasks/T678.md) backendの残骸を撤去しruffを導入する 規模S
- [x] [T679](tasks/T679.md) fetch骨格・ポーリング・Popoverの共通化取り残しを片付ける 規模M
- [x] [T680](tasks/T680.md) JST定数・バッジ語彙・ロガー命名を正準化する 規模S〜M
- [x] [T681](tasks/T681.md) 設定の保存有無の方針を統一する 規模S
- [x] [T682](tasks/T682.md) バッチの構造的欠陥を直す 規模M
- [x] [T683](tasks/T683.md) テストの空白を埋める 規模S〜M
- [x] [T684](tasks/T684.md) レビュー基盤を是正する（実機確認の場所・記載漏れ） 規模S
- [x] [T685](tasks/T685.md) その他の単発の是正 規模M

## 軸スタジオが判断を助けない（2026-09-08・ユーザー指摘「軸スタジオ使いにくいね・・・直接DBにInsertした方が楽かなって思うくらい」から）

- [x] [T686](tasks/T686.md) 軸スタジオで折れ点の効き方を実データの分布として見せる 規模M

## 軸単体での評価（2026-09-09・ユーザー指摘「原則として、軸単体で評価できるようにしたい」から）

- [x] [T687](tasks/T687.md) 軸単体で経路を評価できるよう、得点の隣に物理量を出す 規模M
- [x] [T688](tasks/T688.md) way_landcoverの増分実行が「未計算」と「計算済み・値なし」を区別できるようにする 規模M
- [x] [T689](tasks/T689.md) 合成軸も軸単体で判断できるようにする 規模M
- [x] [T690](tasks/T690.md) 目的地モードで最短距離ルートを既定で出し、好みのルートとの距離差を示す 規模M
- [x] [T691](tasks/T691.md) 道の蛇行を軸にする（曲がりの少ないルートを選べるようにする） 規模M
- [x] [T692](tasks/T692.md) Edge単位の材料をway単位でも見られるようにする 規模M

## 統合レビュー第6回の指摘（2026-09-10）

[history/2026-09-10_all.md](../.claude/commands/review/history/2026-09-10_all.md)の指摘を
起票単位で24本へ束ねたもの。**過去5回0件だったP0を2件立てた**（最短ルートの0次ハードフィルタ迂回／
CIのドリフト検知が空振り＋masterが5回連続赤）。実施順序に依存関係があり、
とくにT693とT694は他のすべてに先行する（詳細は結果ファイルのPhase 8参照）。

### 第0段: 安全網の回復（他のすべてに先行する）

- [x] [T693](tasks/T693.md) CIの生成物ドリフト検知を回復し、静的軸カタログを再生成する 規模M
- [x] [T694](tasks/T694.md) masterのCIを緑に戻す（蛇行の一次属性がフロントの対応表に無い） 規模S
- [x] [T695](tasks/T695.md) 一次属性の手書き対応表を整理する（略名表は本番の消費者ゼロ） 規模S

### 第1段: 利用者に届いている誤り

- [x] [T696](tasks/T696.md) 目的地モードの「最短」ルートが0次ハードフィルタを迂回する問題を直す 規模S〜M
- [x] [T697](tasks/T697.md) 負の生値を持つ軸で分布プレビューが嘘の分布と正反対の助言を出す問題を直す 規模M
- [x] [T698](tasks/T698.md) 生値の精度をdifficulty用の丸めから分離する 規模M
- [x] [T699](tasks/T699.md) 蛇行軸の配線を最後まで通す（3箇所の欠けが互いの検知を打ち消している） 規模M

### 第2段: 検知の空白を埋める

- [x] [T700](tasks/T700.md) 軸スタジオのバリデータ非対称を是正する（GUI操作で全ルート生成が500になりうる） 規模S
- [x] [T701](tasks/T701.md) 「表示範囲が広すぎます」の案内を軸レイヤーへ配線する 規模S〜M
- [x] [T702](tasks/T702.md) nextを16.3.4へ更新する（critical 1件の解消） 規模S
- [ ] [T703](tasks/T703.md) ポップアップのXSS到達経路を塞ぐ（maplibre-gl `DOM.sanitize()` バイパス、CVSS 10） 規模S＋M
- [x] [T722](tasks/T722.md) タスク提案・着手が対象領域の正本ドキュメントを読むようにする 規模S
- [x] [T723](tasks/T723.md) architecture.mdが撤去済みの名前を断りなく名指ししていないか機械で見る 規模M
- [x] [T724](tasks/T724.md) ドキュメントの棚卸し（重複領域と「実装の翻訳」を削る） 規模L
- [x] [T725](tasks/T725.md) 路面タイルへ道路名（name/ref）を焼き込む 規模S
- [ ] [T726](tasks/T726.md) Supabaseプロジェクトの後始末 規模S
- [x] [T704](tasks/T704.md) 軸カタログ取得失敗を利用者に見せる（重み設定が無言で捨てられる） 規模S〜M
- [x] [T705](tasks/T705.md) review_checks.pyの検知範囲を広げる（検知器自身の適用範囲の穴） 規模M
- [x] [T706](tasks/T706.md) CIが検証するNodeと本番が動かすNodeを揃える 規模S

### 第3段: P2/P3を型ごとに束ねたもの

- [x] [T707](tasks/T707.md) docs乖離の一括是正（architecture.md・design-principles.md・docs/modules全15ファイル） 規模M
- [x] [T708](tasks/T708.md) 削除・改名された事実を語るコメントを一掃する 規模M
- [x] [T709](tasks/T709.md) コード自身が述べる契約と実装の不一致を是正する 規模M
- [x] [T710](tasks/T710.md) テストの空白と偽陽性を是正する 規模M
- [x] [T711](tasks/T711.md) UI/CSSの重複と未定義トークンを是正する 規模M
- [x] [T712](tasks/T712.md) ensure*関数の再適用強制と、共通骨格の写経取り残しを片付ける 規模M
- [x] [T713](tasks/T713.md) AxisComposer.tsxから折れ点エディタとpayload変換を抽出する 規模M

### DEFER（トリガー未到達）・閾値の承認待ち

- [ ] [T714](tasks/T714.md) precompute系バッチの長時間トランザクションを観測できるようにする 規模S — トリガー: 本番でidle in transaction起因のテーブル肥大化、またはidle_in_transaction_session_timeoutによる中断が実際に観測された時点
- [ ] [T715](tasks/T715.md) 数値入力プリミティブ（NumberField/SliderNumberField）を共有部品へ出す 規模S — トリガー: 3箇所目の「制御された数値入力が入力途中を食う」問題が出た時点
- [x] [T717](tasks/T717.md) 本番へprecompute_edge_curvatureを適用し蛇行軸の欠損を解消する 規模S
- [x] [T716](tasks/T716.md) domain/material_catalog.pyへ規模ウォッチの個別閾値を設定する 規模S
- [x] [T718](tasks/T718.md) カテゴリ材料の内訳（値ごとの延長割合）を出せるようにする 規模M

## 統合レビュー第7回の指摘（2026-09-11）

中心的な発見は**「完了扱いにした是正が目的を果たしていない」が3つ同時に起きていた**こと
（T718が本番で未動作／T703の到達経路列挙が不完全／T724段階3の0件は検知器が黙っているだけ）。
詳細は[history/2026-09-11_all.md](../.claude/commands/review/history/2026-09-11_all.md)。

### 第0段: 到達している実害

- [x] [T727](tasks/T727.md) 区間インスペクタのXSS到達経路を塞ぐ 規模S

### 第1段: 完了扱いの機能が動いていないもの

- [x] [T728](tasks/T728.md) T718の材料内訳を本番で表示されるようにする 規模M
- [x] [T729](tasks/T729.md) ensureLayerFromSpecが凡例フィルタを巻き戻すのを止める 規模M

### 第2段: ガードの射程を実際に合わせる

- [x] [T730](tasks/T730.md) architecture.md検知器の免除条件を絞り、免除分を参考出力する 規模M
- [x] [T731](tasks/T731.md) 静的スコア行列の列集合を読み出し時に検証する 規模M
- [x] [T732](tasks/T732.md) npx()のパス解決を直し、写経の監視をLinuxでも動かす 規模S
- [x] [T733](tasks/T733.md) identifier_existsの小文字化緩和をSettingsフィールドへ限定する 規模S
- [x] [T734](tasks/T734.md) --staged経路の段落判定をインデックス由来の内容で行う 規模S

### 第3段: P2/P3を型ごとに束ねたもの

- [x] [T735](tasks/T735.md) 契約不一致の一括是正（docstring・型・docsが述べる前提の不成立） 規模M
- [x] [T736](tasks/T736.md) 検知・ガードの射程不足の一括是正 規模M
- [x] [T737](tasks/T737.md) 重複・写経の一括是正 規模M
- [x] [T738](tasks/T738.md) fail-openの破れを是正する 規模S
- [x] [T739](tasks/T739.md) 死んだ参照・撤去済みの名前を語る周辺表現の一掃 規模M
- [x] [T740](tasks/T740.md) テストの空白と偽陽性を是正する 規模M
- [x] [T741](tasks/T741.md) ドキュメントと実装のずれを是正する 規模M
- [x] [T742](tasks/T742.md) 残骸の撤去 規模S

### レビュー基盤・閾値・T696の派生

- [x] [T743](tasks/T743.md) レビュー基盤のcontext.mdを現状化する 規模S
- [x] [T744](tasks/T744.md) evaluation.pyへ規模ウォッチの個別閾値を設定する 規模S
- [x] [T745](tasks/T745.md) 目的地モードでmax_routes=1のとき軸の重みが結果に反映されない 規模S〜M
- [x] [T746](tasks/T746.md) LoopRoutingEngineのevaluate_loopsに位置対応の契約を明示する 規模S

## 手書き列挙をやめ、導出で気づく（2026-09-11・ユーザー指摘「チェックのための手書き列挙、やめよう。ルールで気付こう。チェックのための手書きが漏れないための、チェックを考えるのは馬鹿らしい」から）

[design-principles.md](design-principles.md)構造仕様12として明文化した。

- [x] [T747](tasks/T747.md) キャッシュ鍵を1体系にし、導出できるものは手で書かない 規模M
- [x] [T748](tasks/T748.md) 手で列挙している母集団を洗い出し、導出へ置き換える 規模M
- [x] [T749](tasks/T749.md) ドキュメントの要素の数え上げを挙動の記述へ置き換える 規模M

## 修正の仕方そのものを見直す（2026-09-11・ユーザー指摘「あなたは修正するたびに、指摘を増やしています」「修正時の原則、プロセスをまず改善してください」から）

- [x] [T750](tasks/T750.md) 修正の原則を明文化し、完了前チェックの自己申告分を畳む 規模M
- [x] [T751](tasks/T751.md) 「未起票の残り」を検知器にする 規模S
- [x] [T752](tasks/T752.md) 周期レビューの個票を、起票したタスクが参照できる形で残す 規模S
- [x] [T830](tasks/T830.md) タスク番号の衝突を検知器にする 規模S

## ルート生成→結果確認→比較の導線レビュー（2026-09-12・本番実機、ユーザー指示「/review:uiの観点に限らず気になったことをすべて」）

本番URLをPlaywright（headless Chromium）でデスクトップ1280px・モバイル390pxの両方から操作し、
周回生成→候補確認→重み変更→再生成→研究モードの比較→目的地モードまでを実測した。
指摘の個票は[history/2026-09-12_ui.md](../.claude/commands/review/history/2026-09-12_ui.md)参照。

- [x] [T754](tasks/T754.md) 災害レイヤーの既定ONが地図全面を塗り、レンズ配色と衝突してルート線が見えない 規模M
- [x] [T755](tasks/T755.md) モバイルで生成直後のルートがボトムシートの下に隠れる 規模S
- [x] [T756](tasks/T756.md) 本番の地図初期表示が「地図を読み込み中」のまま長時間止まる 規模M
- [x] [T757](tasks/T757.md) ヘッダーの観測値取得エラーが常駐し、モバイルではヘッダーが画面外へ溢れる 規模S〜M
- [x] [T758](tasks/T758.md) 生成中・エラー・候補0件のフィードバックが操作している場所から見えない 規模M
- [x] [T759](tasks/T759.md) 候補一覧の一覧性: タブの溢れ・数値の比較・地図からの選択 規模M〜L
- [x] [T780](tasks/T780.md) ルート結果の2カラムに余白が残り、指標の並びが高い 規模S
- [x] [T781](tasks/T781.md) ピンを置けるのは「ルート設定」を見ている間だけにする 規模S
- [x] [T782](tasks/T782.md) 軸チップをアイコン主体にして内訳の縦を詰める 規模S
- [x] [T783](tasks/T783.md) 有効な軸のアイコンが白く、無効な軸だけ色が残る 規模S
- [x] [T784](tasks/T784.md) ルート設定パネルを「条件／重み／除外」の3タブへ 規模M
- [x] [T785](tasks/T785.md) 下部シートの高さを、利用者が決めた高さとして覚える 規模S
- [x] [T788](tasks/T788.md) 重みタブから余白と操作を削り、軸の説明をチップへ戻す 規模S
- [x] [T789](tasks/T789.md) 「条件」タブの入力値を次回も引き継ぐ 規模S
- [x] [T791](tasks/T791.md) 画面のベタ書き説明文を情報アイコンの奥へ寄せる 規模S
- [x] [T794](tasks/T794.md) 重みタブの見出し・合計表記・既定値ボタンを落とす 規模S
- [x] [T796](tasks/T796.md) 起票の瞬間に、既存の未完了エントリとの重なりを機械的に出す 規模S
- [x] [T797](tasks/T797.md) 出発地・経由地・目的地を同じ形で置けるようにする 規模M
- [x] [T803](tasks/T803.md) 常設ヘッダーのバーを短くする（日の出・日没は「今日」パネルへ） 規模S
- [x] [T804](tasks/T804.md) 地点のピンを3つとも「つかんで動かせる」形に揃え、地図の操作ボタンをシートの上へ出す 規模S〜M
- [x] [T806](tasks/T806.md) 地点の印を地図のピンと同じ図形にし、候補数は消さず押せない状態で残す 規模S
- [x] [T807](tasks/T807.md) 区間を合成して作ったルートの結果が、押した場所から見えない 規模S
- [x] [T829](tasks/T829.md) 動的気象タイルの切り替えで、MapLibreが「ArrayBuffer is detached」を吐く 規模S
- [ ] [T808](tasks/T808.md) ルート結果から続く編集導線（元を固定し、区間ごとに全候補の代替から選ぶ） 規模L
- [x] [T769](tasks/T769.md) ルート結果を「見る」と「作る」に分ける 規模M〜L
- [x] [T777](tasks/T777.md) フルスイートでのみ落ちるテスト（テスト間で共有されるprocess.env） 規模S
- [ ] [T779](tasks/T779.md) 生成結果を「素材」、編集の結果を「採用ルート」として分ける 規模M〜L
- [x] [T778](tasks/T778.md) 下部シートの既定の高さを中身へ合わせる 規模S
- [x] [T776](tasks/T776.md) ルート結果の軸チップを、ルート設定の軸チップと同じ形に揃える 規模S
- [x] [T775](tasks/T775.md) 軸別難易度の一覧を畳み、寄与度の凡例チップを詳細の入口にする 規模M
- [x] [T773](tasks/T773.md) ルート結果タブの中身を減らす 規模M
- [x] [T774](tasks/T774.md) ルート結果ヘッダの操作アイコンが小さく、閉じる✕と紛れる 規模S
- [x] [T760](tasks/T760.md) ルート結果パネルの表記品質（単位の二重表示・意味の無い合計・はみ出し・説明の矛盾） 規模S〜M
- [ ] [T854](tasks/T854.md) 生成したルートを保存して、後から呼び出せるようにする 規模M〜L
- [x] [T761](tasks/T761.md) 目的地モードの目的地チップの状態表示と、生成後の地図タップの挙動 規模S〜M
- [x] [T762](tasks/T762.md) 研究モード「比較」タブの空状態・表の幅・再生成後の表示 規模M
- [x] [T770](tasks/T770.md) ルート線が面レイヤーの上で読めない（縁取りが無い） 規模S

## 開発ループの待ち時間（2026-09-12・ユーザー指摘「UIテストが非常に時間がかかりネック」から）

- [x] [T767](tasks/T767.md) vitestのsetupFilesがDOM不要のテストにも課金している 規模S
- [x] [T772](tasks/T772.md) テスト実行の壁時計を決めているのはhappy-dom環境の構築 規模S
- [x] [T768](tasks/T768.md) UI検証の導線を毎回書き直している 規模S〜M

## 統合レビュー第8回の指摘（2026-09-13・ユーザー指示「t790周りも全てレビュー対象にして」）

中心的な発見は**「正しく実装したのに、正しさの根拠となる記述を置き去りにした」**が
backend・frontend・docsで同時に起きていたこと。実装とテストが正で、ドキュメントと
コメントが古い——という向きが一貫しており、実害は「次に触る人が、直したばかりの欠陥を
戻す」ことに集まる。詳細は
[history/2026-09-13_all.md](../.claude/commands/review/history/2026-09-13_all.md)、
個票202件は
[history/2026-09-13_all_shards.md](../.claude/commands/review/history/2026-09-13_all_shards.md)。

### 第0段: 検証を先に置く／到達している実害

- [x] [T809](tasks/T809.md) レンズのしきい値上書きが、ルート前後で別の物差しとして読まれる 規模M
- [x] [T831](tasks/T831.md) 段階の体感ラベルが、ルート後の凡例では使われない 規模S
- [x] [T833](tasks/T833.md) 停止密度の折れ線が早く飽和し、上位の段階が区別できない 規模S
- [ ] [T856](tasks/T856.md) 折れ点が実データの分布と合っていない公開軸が3つある 規模M
- [x] [T812](tasks/T812.md) 時刻ビンを渡す探索経路にテストを置き、逆向き木の制約を実装で表明する 規模S

### 第1段: 境界を固定する（記述の一掃より先に検知を広げる）

- [x] [T810](tasks/T810.md) T790が置き換えた前提を語る記述を一掃し、死んだ識別子の検知をコード内コメントへ広げる 規模M
- [x] [T813](tasks/T813.md) キャッシュ鍵の署名が拾えていない2つの穴を塞ぐ 規模M
- [x] [T814](tasks/T814.md) 鮮度台帳がbatchをトップレベルimportする依存を断ち、台帳の網羅性の穴を塞ぐ 規模S〜M
- [x] [T832](tasks/T832.md) road_edges・road_nodesへ書く事前計算の陳腐化が、どこにも現れない 規模M
- [x] [T836](tasks/T836.md) 「鮮度」タブが、読めない・押すまで何も無い・直した後にどうすればよいか分からない 規模M
- [ ] [T839](tasks/T839.md) 派生データの作り直しを、管理画面から要求できるようにする 規模L
- [x] [T840](tasks/T840.md) 本番DBの状態を「鮮度」タブから見えるようにする 規模L
- [x] [T842](tasks/T842.md) コードの書式を機械に決めさせる（prettierの導入、段階適用） 規模M
- [x] [T844](tasks/T844.md) 鮮度台帳が出すコマンドが、そのまま打つと本番へ効かないか本番を止める 規模S
- [x] [T845](tasks/T845.md) 本番DBの状態が、何を母数にした何件なのか読めない 規模S〜M
- [x] [T846](tasks/T846.md) 「鮮度」タブの名前が、中身の一部しか指していない 規模S
- [x] [T847](tasks/T847.md) 材料キャッシュの世代を、コード定数ではなくDBを正にする 規模M
- [x] [T848](tasks/T848.md) タイルへ焼き込む世代だけ、いまも手で上げる運用が残っている 規模M
- [x] [T849](tasks/T849.md) 鮮度台帳が、バッチの対象外の行を「未計算」と数え続ける 規模S〜M
- [x] [T850](tasks/T850.md) 標高が、何度作り直しても48件だけ埋まらない 規模M
- [x] [T851](tasks/T851.md) 「DBの世代とディスクの記録を突き合わせて捨てる」仕組みが2つある 規模M
- [x] [T852](tasks/T852.md) JMAタイルの配信障害が、地図の上では「危険度ゼロ」と見分けられない 規模M

### 第2段: 利用者に届いている誤り

- [x] [T811](tasks/T811.md) 撤去済みMapLayersPanelへの参照を一掃し、地図チップの案内文を実際の入口へ向ける 規模S〜M
- [x] [T815](tasks/T815.md) 目的地の補正で生成直後にdirty印が点灯するのを直す 規模S
- [x] [T818](tasks/T818.md) 周回モードの候補一覧にも所要時間の比較材料（最速の印・+N分）を出す 規模S

### 第3段: 正本を実態に合わせる

- [x] [T816](tasks/T816.md) 設計原則「消さずに薄くする」の適用範囲を、T783のユーザー判断に合わせる 規模S
- [x] [T817](tasks/T817.md) penalty_strengthの既定値を片側importへ寄せ、回帰テストを置く 規模S

### 第4段: P2/P3を型ごとに束ねたもの

対象の一覧は各エントリ本文が持つ（[T735](tasks/T735.md)が個票を復元できず対象を確定できない
まま残った失敗を繰り返さないため）。**T810を先に入れると、T822の「実在しない識別子の名指し」は
機械的に拾える**ので、その順で進める。

- [x] [T819](tasks/T819.md) T790/T769が残したコード側の残骸を撤去する 規模M
- [x] [T820](tasks/T820.md) 無言のフォールバック・失敗の握り潰しを是正する 規模M
- [x] [T821](tasks/T821.md) 同じ規則が複数箇所へ書き写されている箇所を1つへ寄せる 規模M
- [x] [T822](tasks/T822.md) ドキュメントと実装のずれを是正する（第8回ぶん） 規模M
- [x] [T823](tasks/T823.md) 契約を検証していないテスト・誤った挙動を固定するテストを是正する 規模S〜M
- [x] [T824](tasks/T824.md) 数え上げ（個数・全件列挙）をやめ、増減に耐える書き方へ 規模M
- [x] [T825](tasks/T825.md) 無駄な再描画・再計算を止め、再描画経路の網羅を保証する 規模S〜M
- [ ] [T972](tasks/T972.md) 取り直せないデータ（軸定義等の管理データ）のバックアップを持つ 規模M
- [ ] [T971](tasks/T971.md) ソース内へベタ宣言した「外部が決めた対応表」を振り分ける 規模M
- [ ] [T970](tasks/T970.md) データの置き場所と形を決め直す（生データ・派生データの分類と形） 規模L
- [ ] [T969](tasks/T969.md) アーキテクチャの総点検（層の責務・到達可能性・知識の重複・検知器とレビュー基盤の棚卸し） 規模L
- [ ] [T968](tasks/T968.md) 層ごとの責務（DB=データ／app=ふるまい／テスト=今のふるまい）を点検する 規模M
- [ ] [T967](tasks/T967.md) 経緯コメントの残りを引き取る（T567完了後に残った61件、T826の2ファイルを除く） 規模M
- [ ] [T826](tasks/T826.md) axisLayers.ts・secondaryAxes.tsの経緯コメントを一掃する 規模S — トリガー: この2ファイルを実装目的で次に編集するとき

### 規模ウォッチ

6件発火し、`MapView.tsx`・`road_graph_engine.py`・`page.tsx`を(b)抽出、
`routing.py`・`evaluation.py`・`icons.tsx`を(a)理由つきKEEPへ分類した。閾値は
ユーザー承認のうえ`size_watch.json`へ書き戻した（MapView 4,000／road_graph_engine 2,700／
page.tsx 2,600／routing.py 1,400を新規付与）。**抽出そのものは未起票**——今期の実害は
すべて記述の側から出ており、分割は上記の是正が済んでから判断する。

## 実走フィードバック（2026-09-13・ユーザー実走報告「交通量が多い道を突っ切ったり、右折する［車線を跨ぐ］コストがばかにならなかった」「たまに凸凹したよくわからない回り道があった」「生活道路をぐるぐる走るので非常に気を遣った」から）

- [x] [T790](tasks/T790.md) 評価基準の単位を決め直す（所要時間＋主観的割増） 規模L〜XL
- [x] [T798](tasks/T798.md) 結論ありきで面倒な改修を先延ばしにする傾向を、プロセスで止める 規模S〜M
- [x] [T792](tasks/T792.md) A*のヒューリスティックが実データで効いていない 規模S〜M
- [x] [T793](tasks/T793.md) ベンチマークの変更で本番backendがデプロイされる 規模S
- [x] [T863](tasks/T863.md) ベンチマークの起動は明示的にし、測ったコミットを記録する 規模S
- [x] [T799](tasks/T799.md) 評価基準の較正（物理を写した軸の重み・主観のレート・路面） 規模M
- [x] [T805](tasks/T805.md) 走行モデル・ターン・停止の暫定値を管理画面から変えられるようにする 規模M〜L
- [x] [T800](tasks/T800.md) 交差点ノードの属性を事前計算する（信号の有無・接続する道の最大階級） 規模M
- [ ] [T801](tasks/T801.md) ターンの費用を較正する 規模S〜M
- [x] [T881](tasks/T881.md) 蛇行軸を、ターン費用ができた今の前提で見直す（存廃を含む） 規模M
- [x] [T802](tasks/T802.md) 時刻ビンが1本のときに2点間探索の手間を省く 規模S
- [x] [T827](tasks/T827.md) 目的地ルートが0件のとき、警告が原因を誤って名指しする 規模S
- [x] [T828](tasks/T828.md) MSMの「配信が滞っています」が、正常運用でも定期的に点灯する 規模S
- [x] [T834](tasks/T834.md) CIのpostgisテストが2日間赤のままだった（実装変更にテストが追随していない2件） 規模S
- [x] [T835](tasks/T835.md) CIだけが実行するテストの赤に、次のCIログを開くまで気づけない 規模S
- [x] [T853](tasks/T853.md) masterのCI警告が、同じコミットが緑でも鳴る 規模S
- [x] [T837](tasks/T837.md) 区間の乗り換えで、代替の距離差と評価結果が両立しない 規模S〜M
- [x] [T838](tasks/T838.md) 区間の乗り換えが「他ルート1本と丸ごと入れ替え」になり、複数ルートを乗り継げない 規模M
- [x] [T841](tasks/T841.md) 地図でできることを、いま見ているパネルが持つ操作だけにする 規模S〜M
- [x] [T843](tasks/T843.md) 乗り換え先の道の上にある分岐へ、そのまま乗り継げるようにする 規模M

## 総合難易度と負荷の位置づけ（2026-09-14・ユーザー指摘「総合難易度の位置づけが分からなくなってきた。負荷で代替してよくない？」から）

- [x] [T855](tasks/T855.md) 難易度の帯へ距離の次元を与え、面積で負荷を表す 規模M

## 勾配の面レイヤーが地形によらず単色（2026-09-14・ユーザー指摘「地図上のレイヤオンにしても全面青、レンズで選んでも全道灰色」から）

- [x] [T857](tasks/T857.md) 勾配の面レイヤー（環境グループ）を撤去する 規模M

## 線レイヤーの凡例・色分け（2026-09-15・ユーザー指摘「道路種別とか、太さで言われても他とズレている。線レイヤ全般の凡例色分けを見直してほしい。シンプルなルールにして」から）

- [x] [T858](tasks/T858.md) 線レイヤーの視覚言語を「意味を運ぶのは色だけ」へ揃える 規模M
- [x] [T859](tasks/T859.md) 動的気象レイヤーの共有時刻が「今」に追従せず、降水が黙って消える 規模M
- [x] [T861](tasks/T861.md) 観測しか持たないレイヤーが、配信の遅れのぶんだけ常に時刻範囲の外にある 規模S
- [x] [T862](tasks/T862.md) 走行条件のポップオーバーがスマホ幅で画面外へ出る 規模S
- [x] [T865](tasks/T865.md) 一方通行レイヤーが、上下線の分かれた道の片側まで塗っている 規模M
- [x] [T869](tasks/T869.md) ラウンドアバウト等の暗黙の一方通行を、探索が知らない 規模S

## 面レイヤーが地図を覆う（2026-09-15・ユーザー指摘「降雨や災害レイヤで色がつくと、色が濃すぎて地図がほぼ見えなくなる」「色と言うより透明度の調整かな」から）

- [x] [T860](tasks/T860.md) 面レイヤーの不透明度を1つの値へ揃え、地図が読める濃さまで下げる 規模S

## DB変更作業の複雑さ（2026-09-15・ユーザー指摘「migration方式ではなく、apiでDB更新できる方式を検討したほうがいいか。。DB変更作業が無駄に複雑になっている気がしている」から）

- [ ] [T864](tasks/T864.md) 軸の行データは本番を正本にし、反映手順を2段にする 規模M

## 再描画でramp軸のレイヤーが落ちる（2026-09-15・ユーザー報告のコンソールログから）

- [x] [T866](tasks/T866.md) 再描画のたびにramp軸のレイヤーが「ソースが無い」で落ちる 規模S

## デバッグログの受け渡し（2026-09-15・ユーザー要望「デバッグログモードも簡単にコピペできるようにして。コピペボタンは簡易なアイコンにして」から）

- [x] [T867](tasks/T867.md) デバッグログを1押しでコピーできるようにする 規模S

## 区間インスペクタの読みにくさ（2026-09-15・ユーザー指摘「地図上の道をクリックして出てくる詳細画面、一次属性全軸の内訳表示がみにくい」から）

- [x] [T868](tasks/T868.md) 区間インスペクタを、ルート結果と同じ読み方へ揃える 規模M

## 統合レビュー第9回の指摘（2026-09-15）

指摘の一次出力は[history/2026-09-15_all_shards.md](../.claude/commands/review/history/2026-09-15_all_shards.md)、
統合後の判断は[history/2026-09-15_all.md](../.claude/commands/review/history/2026-09-15_all.md)にある。
P0/P1のほぼ全件が「再発防止のために作った仕組みが、母集団を手で列挙しているため効いていない」
という1つの型へ収束した。実施順序は T871 → T872（検知器が出す全件）→ T870 → T875 → T873・T874 を推奨。

- [x] [T870](tasks/T870.md) 派生データ世代のガードを、材料を実際に読む経路へ移す 規模S〜M
- [x] [T871](tasks/T871.md) 再発防止の検知器3種の母集団を、手書きの列挙から性質の導出へ変える 規模M
- [x] [T878](tasks/T878.md) 一次属性cyclewayのshared=Trueが今も要るかを判断する 規模S
- [x] [T872](tasks/T872.md) 再描画で「クリックした道の強調」だけが消えて戻らない 規模S
- [x] [T873](tasks/T873.md) 「今」ボタンを張り付き復帰へ配線し、dirty印の誤点灯を止める 規模S
- [x] [T874](tasks/T874.md) 区間編集中に候補をクリアすると、地図の操作が無言で死んで復帰できない 規模S
- [x] [T875](tasks/T875.md) T865の本番バックフィルを実施し、残りを起票し直す 規模S
- [x] [T879](tasks/T879.md) 上下線分離の判定条件1（`carriageway`タグ）を、次回のPBF再取込で生かす 規模S
- [x] [T880](tasks/T880.md) docs検査1回の所要を短くする（mutateが10分規模になっている） 規模M
- [x] [T876](tasks/T876.md) 「一掃」タスクの完了条件を、本文の列挙ではなく検知器0件で表す 規模S
- [x] [T877](tasks/T877.md) MapView.tsxのルート描画系を別ファイルへ抽出する 規模M

## 検査が見ていない範囲（2026-09-16・ユーザー指摘「重複検知のライブラリ何か入れてなかった？」から）

- [x] [T882](tasks/T882.md) コピペ検出が、リポジトリで最も大きいファイルを黙って走査していない 規模S
- [x] [T883](tasks/T883.md) 同じ名前をモジュール直下で2回定義しても、どの検査にも引っかからない 規模S
- [x] [T884](tasks/T884.md) テストの足場が写経で膨らんでいる 規模M
- [x] [T885](tasks/T885.md) 開放度の軸が、並木道と市街地を同じ点数にしている 規模M
- [x] [T886](tasks/T886.md) 周囲の土地被覆が、どこにも表示されない 規模M
- [x] [T888](tasks/T888.md) 静的な地図レイヤーの追加が、1箇所で済まない 規模M
- [x] [T887](tasks/T887.md) 土地被覆の材料を、1クラス＝1材料で足せる形にする 規模M

## 統合レビュー第10回の指摘（2026-09-16）

指摘の一次出力は[history/2026-09-16_all_shards.md](../.claude/commands/review/history/2026-09-16_all_shards.md)、
統合後の判断は[history/2026-09-16_all.md](../.claude/commands/review/history/2026-09-16_all.md)にある。
P0は性格が2つに分かれる——本番で機能が壊れている（軸スタジオの分布プレビュー）ことと、
それを見つけるはずの検知器が構造的に見つけられないこと。実施順序は
T889 → T890（測れる状態を先に作る）→ T892（実装の掃除）→ T891（検知器）→ T893 →
T894 → T895 → T896 → T897・T898 を推奨。

- [x] [T889](tasks/T889.md) 軸スタジオの分布プレビューが本番で必ず500を返す 規模S
- [x] [T890](tasks/T890.md) 検知器が「取りこぼしていない」ことを測れるようにする 規模M
- [x] [T891](tasks/T891.md) 検知器の母集団を是正する（コメント除外・記法の絞り込み撤去・リンクのパス解決） 規模M
- [x] [T892](tasks/T892.md) 撤去した軸「開放度」を現行として名指しする記述を掃く 規模S
- [x] [T893](tasks/T893.md) 関数の引数の個数ずれを検知器にする 規模M
- [x] [T894](tasks/T894.md) 冷パスで作ったグラフに交差点属性が載らない 規模M
- [x] [T895](tasks/T895.md) 土地被覆タイルの世代がラスタ構成を含まないのに、immutableで24時間配っている 規模S
- [x] [T896](tasks/T896.md) T886で足した土地被覆レイヤーが、3つの別々の形で整合を欠いている 規模S
- [x] [T897](tasks/T897.md) T422の前提（排他ドメイン）が消滅している 規模S
- [x] [T909](tasks/T909.md) 一時停止・車止めのある無信号交差点で、待ちを二重に数える 規模M
- [x] [T910](tasks/T910.md) 最寄りNodeの探索が、条件に合うNodeが無いとき総当たりへ落ちる 規模S
- [x] [T911](tasks/T911.md) 外縁のケースが違反として成立していなくても、GAPに見える 規模S〜M
- [x] [T901](tasks/T901.md) 外縁のケースが母集団の内側に書かれても、初日からCOVEREDに見える 規模S
- [x] [T900](tasks/T900.md) backendのCIが、同じコードでも通ったり落ちたりする 規模M
- [x] [T899](tasks/T899.md) 既定ONのレイヤーを、性質からではなく1つずつ手で書いている 規模S
- [x] [T898](tasks/T898.md) T567の「15モジュール全て完了」が、T826の残存45件と矛盾している 規模S

### 第2段: P2/P3を型ごとに束ねたもの

- [x] [T903](tasks/T903.md) 正本の文書が壊れている・実装に追従していない 規模S
- [x] [T904](tasks/T904.md) コード自身が述べる契約と、実装が食い違っている 規模M
- [x] [T905](tasks/T905.md) レビュー基盤自身が、どの計測の母集団にも入っていない 規模M
- [x] [T906](tasks/T906.md) 走行モデルと探索に、小さな不整合が残っている 規模M
- [x] [T907](tasks/T907.md) 土地被覆・タイル配信の後始末 規模S
- [x] [T908](tasks/T908.md) 数え上げ・UIの小物・残りのP3 規模S

## 土地被覆が都心で一律グレー（2026-09-16・ユーザー報告「ONにしても地図上一律グレー色背景が付くだけ」から）

- [x] [T902](tasks/T902.md) 土地被覆レイヤーが、都心では一律のグレーにしかならない 規模S

## 面レイヤーの薄い色が読めない（2026-09-17・ユーザー指摘「降雨等の面レイヤの表示透明度を上げた結果、基礎地図は見やすくなったが、少雨等のもともと薄めの色が見えにくくなった」から）

- [x] [T912](tasks/T912.md) 面レイヤーの薄い色が、基礎地図を読ませるための不透明度に潰される 規模M
- [x] [T913](tasks/T913.md) 面レイヤーの差し込み位置を、並び順ではなくタイルスキーマの語彙から導く 規模S
- [x] [T914](tasks/T914.md) 標高の面レイヤが、勾配の無い所まで塗りつぶす 規模M
- [x] [T915](tasks/T915.md) 地図は連続補間、凡例は離散の色見本で、帯の中ほどの色が一致しない 規模S
- [x] [T916](tasks/T916.md) 起伏の陰影が、関東平野の傾きでは出ていても気づけない 規模S

## 区間（edge）単位の情報をフロントが持つ（2026-09-17・ユーザー指摘「edge単位の情報をフロントが知っていたほうがいいこともあるのではないか。区間毎の向かい風、区間毎の予想速度や時間など」から）

- [x] [T917](tasks/T917.md) 路面タイルをedge単位にしたときの費用を測る 規模S
- [ ] [T918](tasks/T918.md) 路面タイルの単位を、区間が読めるズームでは区間（edge）にする 規模L
- [x] [T919](tasks/T919.md) 土地被覆のクラス別割合を区間単位で持つ 規模M

## 勾配レンズの段階が粗く、ほぼ平坦な道が一色で埋まる（2026-09-17・ユーザー要望「クライマーは斜度1%単位で気にする。今だと粗すぎる」「レンズの凡例にも凡例毎にチェックオンオフして表示対象を絞りたい」から）

- [x] [T920](tasks/T920.md) レンズ凡例の段階ごと表示ON/OFFを、ルート確定前の全道路の塗りにも効かせる 規模M
- [x] [T922](tasks/T922.md) 軸スタジオで段階を設計できるようにする（しきい値のまとめ入力とプレビュー） 規模M
- [x] [T923](tasks/T923.md) 確定した軸定義を差分付きで開発DB・本番DBへ配るスクリプトを作る 規模M
- [x] [T924](tasks/T924.md) 軸の更新を1画面にする（ウィザードを撤去し、依存は表示の切り替えで表す） 規模M〜L
- [ ] [T925](tasks/T925.md) 較正を更新から分け、実データが主役の画面にする 規模M
- [x] [T926](tasks/T926.md) 公開済み軸の「表示だけ編集」が保存できない（categoryを定数で上書きしていた） 規模S
- [x] [T927](tasks/T927.md) backendのログ時刻が、どの時間帯かを名乗らないままUTCで出ている 規模S
- [x] [T930](tasks/T930.md) 直角に近い道路の勾配を、0%（平坦）として配っていた 規模S
- [x] [T932](tasks/T932.md) 道の急さを、方位に依存しない表示として持つ 規模M
- [x] [T931](tasks/T931.md) 幹線道路に実地ではあり得ない勾配が付く 規模M
- [x] [T933](tasks/T933.md) 平面のST_Azimuthを方位として使っている箇所が残っている 規模S
- [ ] [T928](tasks/T928.md) タイル世代が上がった瞬間、視界のすべてを取り直して詰まる 規模M
- [x] [T929](tasks/T929.md) キャッシュ世代まわりの欠陥3件（繰り返し全消去・未実装の宣言・掃除の無い置き場） 規模M
- [ ] [T921](tasks/T921.md) 勾配レンズの段階を1%刻みへ細かくし、配色を0（平坦）を境に分ける 規模M

## 地図の点が、実物の単位で見えていない（2026-09-18・ユーザー指摘「地図上の停止要因レイヤにでてくる信号を、同じ交差点ならまとめられない？」「補給休憩についても、自販機とか大量に点プロットされるけど本当にこんなにある？って感じがしている」から）

- [x] [T934](tasks/T934.md) 信号の点が、1交差点あたり2.58個のまま地図へ出ている 規模M
- [x] [T935](tasks/T935.md) 補給POIが、種別を絞らず間引きもせず全点描かれる 規模M

## 統合レビュー第11回の指摘（2026-09-19）

指摘の一次出力は[history/2026-09-19_all_shards.md](../.claude/commands/review/history/2026-09-19_all_shards.md)、
統合後の判断は[history/2026-09-19_all.md](../.claude/commands/review/history/2026-09-19_all.md)にある。
P0は0件で、P1 8件はいずれも「正しく撤去した先」で起きている——フォールバック・ウィザード・
手書きの世代定数・手書きの母集団を消した所に、縮退時の観測可能性／state同期／撤去済みの名前／
記法という形で残った。実施順序はT936（検知器が落ちる状態を先に作る）→ T937 → T938 → T939 →
T940 → T941 → T942 → T943 を推奨。

- [x] [T936](tasks/T936.md) 検知器の「既知のGAP」を落ちるようにし、記法と母集団の穴を塞ぐ 規模M
- [x] [T937](tasks/T937.md) 軸スタジオで、既存軸の折れ点が入力に触れただけで作り直される／再公開の成功が失敗と表示される 規模S
- [x] [T938](tasks/T938.md) 軸カタログの取得が失敗すると、静的な道路レイヤーが全部消え、理由が画面に出ない 規模S〜M
- [x] [T939](tasks/T939.md) レンズ凡例の段階が、ルート前後で別系統のキー・別の表記で作られている 規模M
- [x] [T940](tasks/T940.md) 較正値`evaluation.penalty_strength`の`RESTART`が実現不能で、管理画面は効かない値を「効いている」と表示する 規模S
- [x] [T941](tasks/T941.md) 区間インスペクタだけが土地被覆をway単位で読み、地図の色と内訳が食い違う 規模M
- [x] [T942](tasks/T942.md) architecture.mdにT805（較正値）・edge_landcover・tile_version_serviceが存在しない 規模S
- [x] [T943](tasks/T943.md) トリガー付きタスク6件の前提が、この期間の完了タスクで無効化された 規模S

### 第2段: P2/P3を型ごとに束ねたもの

P2 60件・P3 92件のうち、第1段（T936〜T943）が扱うのはP2 12件だけだった（機械的に点検した）。
残りを型ごとに束ねる。**対象は各タスク本文へ列挙せず、結果ファイルの該当節と
[history/2026-09-19_all_shards.md](../.claude/commands/review/history/2026-09-19_all_shards.md)を指す**。
T951（残りのP3）はT936の検知器の是正が入ってから着手する。

- [x] [T944](tasks/T944.md) キャッシュと世代の後始末（T848・T929の射程の外に残ったもの） 規模M
- [x] [T945](tasks/T945.md) 静的レイヤー追加の1本道化の残り（T888の未実施射程を含む） 規模L
- [x] [T946](tasks/T946.md) 較正値（T805）の後始末 規模M
- [x] [T947](tasks/T947.md) 軸スタジオの後始末（T922・T924・T926） 規模S〜M
- [x] [T948](tasks/T948.md) 表示の語彙と、レイヤー境界の小物 規模M
- [x] [T949](tasks/T949.md) コード自身が述べる契約と、docsの乖離を掃く 規模M
- [x] [T950](tasks/T950.md) 検知器基盤の残り（T936の射程の外） 規模S〜M
- [x] [T951](tasks/T951.md) 残りのP3（撤去済み識別子のコメント・数え上げ・デッドコード・空回りのテスト） 規模S
- [x] [T952](tasks/T952.md) 規模ウォッチの発火6件に、次の閾値または分割を決める 規模S
- [x] [T954](tasks/T954.md) 勾配レンズで、値を示せない道が濃いグレーで地図を覆う 規模S
- [ ] [T953](tasks/T953.md) MapOverlayControlsの汎用フック2本を切り出す 規模S — トリガー: T945完了後も1,100行超

## 材料の冷パスが伸びている（2026-09-19・本番でルート生成に174秒かかったユーザー報告から）

- [ ] [T955](tasks/T955.md) 材料の冷パスが160秒かかり、バッチのたびに最初の利用者が待たされる 規模M
- [x] [T956](tasks/T956.md) 材料の導出をSQLへ寄せ、受け取りを列にする（T955段階A） 規模L
- [ ] [T957](tasks/T957.md) 軸スタジオで刻んだしきい値が、地図では黙って減ることがある 規模S
- [ ] [T958](tasks/T958.md) 評価が要求する形のまま読める区間テーブルを持つ 規模L — トリガー: T956完了後に冷パスを再測定し残りがまだ問題になる場合
- [ ] [T959](tasks/T959.md) 世代を上げた直後に主要エリアのタイルを先に焼く 規模M
- [x] [T960](tasks/T960.md) 材料の導出SQLに、人が書いた期待値のテストが無い 規模S
- [ ] [T961](tasks/T961.md) 土地被覆のway単位フォールバックが、代用したことを言わない 規模S
- [ ] [T962](tasks/T962.md) 「交差点」を、区間単位とway単位で違う母集団から数えている 規模M
- [ ] [T963](tasks/T963.md) コードが増え続けていることを、誰も見ていない 規模S
- [ ] [T965](tasks/T965.md) 「一本化した」と書いた過去の改修が、本当にそうなっているかを棚卸しする 規模L
- [ ] [T966](tasks/T966.md) 29本の検知器が、合わせて何を覆っているかを誰も見ていない 規模M
