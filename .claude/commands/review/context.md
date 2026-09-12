# RideCompass プロジェクト固有レビューコンテキスト

最終更新: 2026-09-12

レビュー実行時に参照するプロジェクト固有情報。詳細仕様の写しではなく
「レビューの判断に必要な構造・思想・履歴」のみを置く。
一次情報が変わったらこのファイルも更新する（更新は /review:improve の提案経由。
ただし一般公開への移行等の大きなフェーズ転換時は improve を待たず更新してよい）。

**鮮度の扱い**: 本ファイルは要約であり陳腐化しうる。とくに「現在の開発フェーズ」節の
タスク状況は **docs/improvement-plan.md を正**とし、レビュー時は必ず最新状態を
そちらで確認する。本ファイルと一次情報が食い違っていたら一次情報に従い、
食い違い自体をレビュー結果の備考に記録する（improve での更新候補になる）。

## アプリケーションの目的

サイクリング向け**周回ルート生成**アプリ。現在地＋目標距離から周回候補を生成し
（折返し点は方位を固定せず、公開軸の重み駆動で選ぶ。`services/road_graph_engine.py`の
モジュールdocstring参照）、標高・風・路面・車の圧迫感等で評価して比較・選択できる。
現フェーズは**評価モデルの研究・精査を優先**（一般公開前のプロトタイプ、個人開発・低利用規模）。

## 構成（現状の姿は docs/architecture.md が正、経緯は docs/decisions/）

- **backend**: FastAPI。`app/api/routers/`（エンドポイント）+ `dependencies.py`（DI工場）→
  `services/`（ユースケース・I/O編成）→ `domain/`（純関数・型。I/Oなし）→
  `infrastructure/`（DB・外部APIクライアント・キャッシュ）。`batch/`（PBF取込等）。
- **frontend**: Next.js App Router + TypeScript + MapLibre GL。`page.tsx` が状態のハブ、
  `MapView.tsx` が地図描画専念。`components/` / `hooks/` / `lib/`（カタログ・純ロジック）/
  `services/`（API呼び出し）/ `types/generated/`（OpenAPI自動生成型）。
- **DB**: PostgreSQL + PostGIS。生OSM層（osm_raw_*）と派生グラフ（road_nodes/road_edges）を分離。
  migrationは `backend/migrations/` の番号付きSQLのみ（create_tablesへのALTER追記禁止）。
  本番はOracle Cloud自前ホスト（関東本土7都県投入済み）、devはネイティブPG18+PostGIS。
- **外部サービス**: GSI標高API/色別標高図・気象庁MSM（予報、S3の静的ファイルを同期）・
  OpenFreeMap（地図タイル、バックエンドプロキシ＋キャッシュ経由）。経路計算自体は外部APIに
  依存しない（自前Road Graph、改善計画T462でopenrouteservice委譲を撤去）。

## 重要なデータフロー

1. **ルート生成** `/api/routes/generate`: `RouteGenerator`（周回戦略・単一実装）が
   `LoopRoutingEngine` ポート（`prepare` / `trace_loop` / `evaluate_loops` の3段階）経由で
   `RoadGraphEngine`（自前Road Graph + Dijkstra、唯一のエンジン実装）へ委譲。
   評価は距離フィルタ通過後の候補のみ（棄却済み候補への無駄な標高取得等を避ける）。
2. **評価は絶対評価1系統**: 区間・Edgeごとのdifficultyと探索コストを、軸定義
   （`axis_definitions`テーブル）の重みから求める。候補集合内の相対スコア（旧`total_score`）は
   撤去済み——リクエスト間で比較できない値を研究UIの実験間比較へ出さないため。
3. **地図レイヤー**: 路面等の静的属性はPostGIS `ST_AsMVT` でMVT生成1系統
   （Overpassフォールバックは撤去済み。カバレッジ外は空タイル＋WARNING）。
   標高はGSIラスタタイル直接参照。
4. **評価軸の追加は1本道**: 軸はDBの行データ（`axis_definitions`テーブル）で、
   軸スタジオのGUI/APIから追加・公開する。材料が新しい場合だけ取込
   （import_profile.yaml / ALLOWED_WAY_TAGS）とdomain側の材料宣言が要る。
   エンジン・フロントのファイルに軸固有の分岐を書かない。**この1本道の具体的な追加点は
   docs/design-principles.md構造仕様3・8が正**（軸ごとのファイル・関数・定数・propを
   新設しない設計になっているかの点検もそこにある）。軸の数・一覧は本ファイルに書かず、
   生成物`axis-catalog.json`または`axis_definitions_snapshot.json`を都度参照する。

## 正準定義と同期機構（レビュー最重点）

- 路面語彙の正準: `domain/road.py`（GOOD/BAD_OSM_SURFACE_TAGS）。SQLはバインドパラメータ参照、
  フロントは生成物 `surface-tags.json` ＋テスト照合。
- highway 3スコープ（取込 / ルーティング可否 / 表示グルーピング）は**意図的に別定義**
  （architecture.md の表参照）。統一提案はしない。変更時は3箇所同時更新か確認する。
- OpenAPI → `types/generated/api.d.ts` 自動生成＋CIドリフト検知。手動同期ペアには
  ドリフト検知テスト必須（MVTレイヤー名・タイル世代等は対応済み）。
- SQLのCASE式（MVTプロパティ）と `domain/traffic.py` 純関数は突き合わせDB統合テストで
  二重実装ドリフトを検知する方式。
- フロントの語彙・色・凡例は`components/Map/`の宣言的カタログ（`mapLayers.ts`・
  `roadFilterAxes.ts`・`routeStyleModes.ts`等）に集約する。コンポーネント内にRecordリテラルの
  対訳表を作らない。軸由来の語彙はbackendの生成物（`axis-catalog.json`）から組み立て、
  フロントに同じ値を手書きしない（片側import）。

## 設計原則（正）

- 設計原則（RideCompass固有の仕様）: **docs/design-principles.md**（唯一の正本、常に最新。
  レビュー時は必ず読む）。判断原則・進め方は本principles.mdの「判断原則」節、一般的な
  実装規約はoverall.md/complexity.mdの各確認観点に集約されている（2026-08-31、
  design-review-2026-08-15.md・complexity-review-2026-08-16.md末尾に分散していた原則を
  仕様/判断/一般規約の3種へ整理・統合）。
- ログ方針: docs/logging.md（エラーは常時WARNING以上、外部I/Oは log_external_call、
  高コスト処理は1行INFOサマリ、座標2桁丸め）。

## 意図的な設計判断（新しい根拠なしに再指摘しない）

docs/complexity-review-2026-08-16.md の **Keep List** が正（ただし「エンジン切替の併存・
`LoopRoutingEngine` 3段階ポート契約」「DI工場が使わない側エンジンの軽量依存も毎回構築」の
2項目は、改善計画T462でopenrouteserviceエンジンを完全撤去しroad_graph単一構成になった
ため前提自体が消滅しており対象外——2026-08-16レビュー本文自体は経緯記録として書き換えない）。
代表例:
- `/api/routes/preview` の残置（Step3疎通確認用）
- `page.tsx` / `MapView.tsx` の分割見送り（肥大化はcomplexity.mdの「規模ウォッチ」で
  横断監視する。MapView.tsxのみ個別の閾値付きKEEPがあり、**現在有効な閾値の正本は
  `history/size_watch.json`の`thresholds`**（タスクT91→T123→T430は登録時点の経緯記録）。特定ファイル個別の閾値は原則新設せず、規模ウォッチの発火→
  精査で判断する）
- Repositoryファサードのフラット委譲契約（対称追加の規約。委譲メソッド削除の提案はT18で棄却済み）
- PBF取込バッチのasyncpg COPY直行（Repository迂回）
- `AxisComposer.tsx`（規模ウォッチの発火が2026-08-27統合レビュー第8回で確認済み、
  T270新設[474行]から3日で1,123行[+137%]。改善計画T355で個別の閾値付きKEEPへ
  昇格——churnが継続中のためすぐには分割せず監視のみ先行する運用。**現在有効な閾値の
  正本は`history/size_watch.json`**（T355は登録時点の経緯記録）
- `road_graph_repository.py` / `road_graph_engine.py`（規模ウォッチの発火が2回連続で
  行き場のないまま繰り返されたため、改善計画T357で個別の閾値付きKEEPへ昇格。**現在有効な
  閾値の正本は`history/size_watch.json`**（T357は登録時点の経緯記録）

## タスク・レビュー履歴の基盤

- **タスク登録**: docs/improvement-plan.md。T番号＋チェックボックス＋
  規模（S=1時間以内/M=半日/L=1日以上）＋トリガー条件。**現在のT番号・進行中/未着手一覧は
  improvement-plan.mdの一覧（インデックス）を都度参照する（本ファイルには具体的な
  番号・件数を書かない。書いた瞬間から陳腐化するため）。2026-08-27、タスク単位の
  ファイル分割を実施済み**: improvement-plan.md本体はチェックボックス付きリンクの
  一覧のみを持ち、各タスクの背景・対応方針・実装メモ・検証結果は
  `docs/tasks/Txxx.md`（未完了・完了を問わず1タスク=1ファイル）にある。
  日付ごとの完了記録アーカイブ（`docs/improvement-plan-archive/`、2026-08-19棚卸で
  新設）は本分割より前の運用で、両者の使い分けは`docs/improvement-plan-archive/README.md`
  の注記を参照。
  レビュー指摘はimprovement-plan.mdへ起票する
  （起票はユーザー承認後）。1タスク=1コミット、挙動変更はテスト先行。
- **基盤構築以前の過去レビュー**（docs/直下、再発チェックの参照元）:
  - docs/design-review-2026-08-15.md（全体設計・第1回）
  - docs/complexity-review-2026-08-15.md（複雑度平衡・第2回）
  - docs/research-interface-review-2026-08-15.md（研究IF・第3回）
  - docs/complexity-review-2026-08-16.md（複雑度平衡・第4回、Keep List。設計原則は
    docs/design-principles.mdへ移設済み）
  - docs/ui-review-2026-08-16.md（UI操作・一般ユーザー目線）
  - docs/external-data-sources-review-2026-08-16.md（外部データ源調査）
- **本基盤構築後のレビュー結果**: `.claude/commands/review/history/` に保存。

## 現在の開発フェーズと今後想定される主要な変更（2026-08-16時点の要約。正は improvement-plan.md）

- ルート生成エンジンはroad_graph一本（2026-08-31のT462でopenrouteserviceエンジンを完全撤去、
  `routing_engine`設定自体が無くなった）。
- 進行中/未着手タスクの一覧はimprovement-plan.mdを都度参照する（本ファイルには転記しない）。
- UIは「研究モード」（`lib/researchMode.ts`、localStorage `ridecompass:research-enabled`で
  切り替える追加UI）と一般ユーザー向けUIの2層。将来的に一般公開UIへ発展させる可能性を持つ。

## 設計書と実装の乖離の見方

- docs/architecture.md は「コード変更と同一コミットで更新」ルールだが、遅れる可能性は常にある。
  consistencyレビューでは記述を無条件に信じず、実装側を一次情報として突き合わせる。
- docs/improvement-plan.md のチェック済みタスクは完了条件（テスト件数green等）が書かれている。
  「チェック済みだが実装が違う」は重要な指摘対象。

## テスト構成

- backend: pytest（件数はテスト実行時に確認。PostGIS統合テストはconftest.pyが接続不可時skip）。
  FakeリポジトリはRepositoryファサードのフラット契約に依存する正式なインターフェース利用者。
- frontend: Vitest（件数はテスト実行時に確認）＋ eslint ＋ tsc。CIに生成物ドリフト検知（api-contract）あり。
- 地図UIの変更確認は**必ずPlaywrightで実機確認**（教訓: research-interface Phase1、
  誤所見の訂正実績は docs/ui-review-2026-08-16.md）。
