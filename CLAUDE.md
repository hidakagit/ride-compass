# RideCompass

サイクリング向け周回ルート生成アプリ。backend（FastAPI）+ frontend（Next.js）。
アーキテクチャ全体は docs/architecture.md 参照。

設計レビュー（2026-08-15〜16）の指摘と改善実行計画は docs/improvement-plan.md にある。
リファクタリング・機能追加の着手前に該当タスクの有無を確認し、完了したらチェックを更新すること。
設計原則10箇条は docs/design-review-2026-08-15.md 末尾を参照。複雑度平衡の追加原則
（評価軸追加の1本道・定数の片側import・UI語彙のカタログ集約等）は
docs/complexity-review-2026-08-16.md 末尾の改訂版が最新。

## 出力言語（必読）

**ユーザーへ見せる結果・メッセージは常にすべて日本語で表示すること。** 対話中の通常の
返信本文（要約・説明・質問・見出し等）はもちろん、バックグラウンドで動くタスク
（Bash/PowerShellのrun_in_background・Agentのdescription・ScheduleWakeupのreason・
CronCreate等）に付随する進捗・ログ・通知メッセージも例外なく日本語にする。英語の技術用語
（ファイル名・コマンド・ライブラリ名等）はそのままでよいが、地の文・説明・見出しは日本語で書く。
（ユーザーから複数回明示指示、2026-08-22にメモリ頼みではなくプロジェクトルールとして
明文化するよう指示された）

## ログ方針（必読）

**コードを追加・変更するときは docs/logging.md のログ方針に従うこと。** 要点:

- エラー・429拒否・候補0件はWARNING以上で**常時**出す（debug_modeはDEBUG詳細の追加スイッチであり、エラー出力の条件にしない）
- 外部API/キャッシュアクセスは `app/infrastructure/debug_log.py` の `log_external_call` で囲む（cache hit/miss・result・statusをfieldsに設定。ログと /api/debug/stats の統計が自動で付く）
- 高コスト処理はステージ別所要時間と中間結果の減り方を1行INFOサマリにする（route_generator.py参照）
- リクエストIDは request_log.py のミドルウェアが全ログへ自動付与する。個別ログに書かない
- 常時出るログの座標は小数2桁へ丸める。APIキーはどのレベルでも出さない

## テスト方針（必読）

**新しいテストを追加するときは docs/testing.md のパターンに従うこと。** 要点:

- レート制限の境界値テストは `rate_limiter.check_rate_limit` を直接呼んで上限-1件を埋め、実HTTPは境界の1〜2回に絞る（上限回数分の実HTTPループ厳禁）
- PostGIS統合テスト（road_graph_session、conftest.py）はファイル単位でエンジン・イベントループを共有する設計。新規ファイルでは `pytestmark = pytest.mark.asyncio(loop_scope="module")` が必要（自前の追加async fixtureにも `loop_scope="module"` を明示）。CIはpytest-xdistで並列化しているため `pytest.mark.xdist_group(name="postgis")` も併せて必須（詳細はdocs/testing.md参照）
- フロントエンドの新規テストがDOM（render/renderHook/window等）を使わない純ロジックなら、ファイル先頭へ `// @vitest-environment node` docblockを付ける（実装側関数の隠れたDOM依存にも注意、詳細はdocs/testing.md参照）

## コミット時の同期ルール（必読）

コード変更と同期して更新すべきペアの漏れが繰り返し発生している（OpenAPI生成物ドリフト
3回・architecture.md未追従5回以上）。以下は**同一コミットで**必ず実施すること
（2026-08-23の棚卸でimprovement-plan.md「進め方の原則」から本ファイルへ昇格。
ルールがCLAUDE.md外にあり実装セッションが読まないことが3回目の再発の根本原因だったため）。

- **backend側のAPIルーター・Pydanticモデル・レジストリ・domain定数を変更したら**、
  `backend/scripts/export_openapi.py`→`cd frontend && npm run generate:api`を実行し、
  `git diff --exit-code -- frontend/src/types/generated/`がクリーンであることを確認する
  （T180・T185・T218の3回のドリフト実績。統合レビュー2026-08-22 T196でルール化、
  2026-08-23にここへ昇格）。
- **規模M以上でAPI・ドメイン概念・レイヤー種を新設するタスクは、完了条件へ
  docs/architecture.md追従を既定で含める**（同型再発が繰り返し検出されたことを受け
  統合レビュー2026-08-22 T197でルール化）。docs（「現状」記述）はコード変更と
  同一コミットで更新する。
- **MVT焼き込み値（CASE式・材料タグ・domain純関数）を変更したら**、対応するタイル世代
  定数（`ROAD_SURFACE_TILE_VERSION`等）と生成物（region-tile-config.json）を同一コミットで
  上げる（T70・T93で対上げ漏れが2回発生）。
- **評価軸（`axis_definitions`テーブル、全14軸）の新規追加・削除は手書きのmigration SQL
  （`backend/migrations/`）で行う。既存の公開軸の`shape_params`（合成ルールの中身：
  重み・breakpoints・参照する材料）を調整する場合は、`axis_admin`のunpublish→PUT API
  （軸スタジオのGUI、または直接API呼び出し）→republishで行う**（改善計画T353、
  2026-08-27）。使い分けの理由: `shape_params`の値そのものは「唯一の正解」が無い
  継続的チューニング対象であり、監査証跡・ロールバック・開発/本番の厳密な一致は
  過剰品質と判断した（必要な担保は`AxisShape`のPydanticバリデーションと
  `check_publish_immutability`のみで足りる）。一方、軸の新規追加・削除（行の増減）は
  他のDBスキーマ変更と同じ標準運用（migration）に合流させ、レビュー可能性を保つ
  （改善計画T350の判断を維持）。`domain/axis_definitions.py: AXIS_DEFINITIONS`の
  Python literalは撤去済みでDBが唯一の正本（T350）。`tests/test_migrate.py`の
  ブートストラップテストは、まっさらなDBへ全migrationを適用した結果が「全軸が例外なく
  読める・未知の材料/軸参照が無い・件数が14で一致する」ことをpostgis統合テストとして
  検証する（DB接続が要るため`pytest -m "not postgis"`実行時はスキップされる。
  ローカルPostgreSQLを起動して`pytest tests/test_migrate.py`を実行し確認すること）。
- **規模M以上の変更は、着手前の最初のコミットでdocs/improvement-plan.mdへ対応する
  タスクエントリを先に作成する**（T130で一度破られ事後是正された実績を受けT135で
  明文化を検討、2026-08-23のT231棚卸で正式採用）。作業内容が変わりうる大きめの
  タスクほど、途中で背景・方針判断が失われやすく、後から遡って記録を作ると
  経緯（なぜその設計にしたか）が失われるため。
- **判断・実行を保留する場合、「後で判断」等の一言メモで済ませず、影響範囲
  （保留することで何がブロックされるか・何が動かなくなるか）を明記した完全な
  タスクエントリとして起票する**（2026-08-23、「本番Oracle DBへのmigration 0013
  適用・標高バックフィル」を「本番DB書き込みを伴うため保留、実行タイミングは
  別途相談」という一言だけで記録した結果、実態が「標高データが多少足りないだけ」
  ではなく「road_graphエンジンが本番で一切起動できない」という重大なブロッカー
  だったことが後続の無関係な調査作業中に突然発覚し、作業が中断・手戻りした実績を
  受けて明文化）。保留の理由だけでなく、保留し続けた場合に次に何が起きうるかを
  一緒に書く。

## 作業ツリーの安全（必読）

このプロジェクトは並行セッション（複数のClaude Codeセッション・エージェント）が同じ作業ツリーを
同時に触りうる。以下を必ず守ること（2026-08-18、レビュー中に他セッションの未コミット変更を
誤って`git checkout --`で破棄してしまう事故が実際に発生したことを受けて明文化）。

- **自分が変更したのではないファイルの変更を作業ツリーで見つけても、絶対に自動で戻さない**
  （`git checkout --`/`git reset`/`git stash`/`git clean`等）。「明らかに別エージェントの
  誤操作に見える」場合でも、まず並行セッションが作業中である可能性を疑う。対応が必要と
  思われる場合は、変更内容を報告してユーザーに確認してから行う。
  `git checkout --`等で破棄した未ステージの変更は、gitオブジェクトとして残らないため
  多くの場合復元不能である。
- **最初から変更を目的としていない作業（調査・分析・レビュー系コマンド等）は、本体の
  作業ツリーではなく専用の `git worktree` で実施する**。読み取り専用の調査であっても、
  本体の作業ツリーを一切変更しない構成にすることで、並行セッションとの衝突・誤操作の
  リスクそのものを無くす。
