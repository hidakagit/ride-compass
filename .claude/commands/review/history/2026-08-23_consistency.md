# 設計・実装・テスト整合性レビュー（2026-08-23）

対象範囲: 前回統合レビュー（`.claude/commands/review/history/2026-08-23_all.md`、対象HEAD
`ba8af57`＝旧履歴での`dd40835`、結果保存コミット`feb1805`）以降〜`origin/master`最新
（`cd52074`）までの8コミット。git-filter-repoによる履歴書き換え後のためコミットハッシュは
旧レビュー記載のものと一致しない（`dd40835`→`ba8af57`に読み替え済み、内容は同一）。

変更ファイル（docsのタスク台帳の棚卸的な移動を除く実コード差分）:
- `backend/app/infrastructure/road_graph_repository.py`（T224）
- `backend/tests/test_road_graph_repository.py`（T224回帰テスト新設）
- `frontend/e2e/smoke.spec.ts`（本レビュー開始前に発見・修正済み、後述）
- `frontend/src/app/page.tsx`・`ComparisonPanel.test.tsx`・`routeApi.test.ts`（T225）
- `frontend/src/types/generated/{api.d.ts,openapi.json}`（T225生成物）
- `CLAUDE.md`（同期ルールの集約、コード変更なし）

ユーザー指示は「実装とテストがずれているところがないか総点検して」であり、直近差分だけでなく
「実装 ↔ テスト」観点を全体に対しても広めに確認した（後述Finding 1・2は範囲外の既存コードが
対象）。

## Executive Summary

直近8コミット自体（T224・T225）は実装・テストとも一致しており問題なし。T224の回帰テストは
「修正前のコードで実際に失敗する」ことまで確認済みで模範的。ただし総点検の過程で、直近差分の
外側に**2件の実質的な「実装とテストのずれ」**を検出した。いずれも今回のセッションで発覚した
T230（CI健全性）・T165/T166 e2eドリフトと同系統の「テストが実際には検証できていない」問題で、
特にFinding 1はCIの信頼性そのものに関わる。

## Findings

### [P1] F-1. CIの`backend`ジョブはPostGIS統合テスト約100件（全体の約9.4%）を実行しておらず、T224の回帰テストもその中に含まれる
- Problem: `.github/workflows/ci.yml`は意図的にPostGISサービスコンテナを立てず、
  `backend/tests/conftest.py`のDB接続不可時skip機構に委ねる設計になっている
  （`ci.yml`コメント「PostGIS統合テストは...接続先DBが無い場合に自動でskipされる設計の
  ため、CIではDBサービスを立てない」）。この設計自体はcontext.md:132に記載された既知の
  選択だが、**「CIが緑＝安全網が機能している」という前提が、統合テスト分のカバレッジに
  関する限り成立しない**ことが、規模の実測とセットで明示的に確認・記録されたことはなかった。
- Evidence:
  - `TEST_DATABASE_URL`を到達不能なホストに向けてCI相当条件でpytestを実行した結果:
    `965 passed, 100 skipped in 55.60s`（DB接続可能な通常実行では`1065 passed`、
    このセッション冒頭のバックグラウンドタスク出力で確認済み）。
  - 直近コミットで追加された
    `test_save_graph_with_way_ids_to_replace_handles_edge_count_beyond_asyncpg_parameter_limit`
    （T224回帰テスト、`backend/tests/test_road_graph_repository.py:135`）を単独指定して
    同条件で実行すると`1 skipped`（`road_graph_repository`フィクスチャ→
    `road_graph_session`→PostGIS依存のため）。
  - T224が修正した不具合（asyncpgプリペアド文パラメータ上限超過による`InterfaceError`、
    road_graphエンジンの再構築経路が都心密度bboxで恒常的に500エラーになっていた実障害）は、
    ユニットテストではなく**実機でのAPI呼び出し中に発覚**した（このセッション内T224実装時の
    経緯）。つまり「CIをすり抜けて本番相当の不具合が出た」実例が、まさにこのskip対象の
    テスト群の守備範囲で既に1回発生している。
  - `docs/improvement-plan.md`・`docs/improvement-plan-archive/`のいずれにも
    「CIへPostGISサービスコンテナを追加する」ことをトリガー付きDEFERとして追跡する
    タスクは存在しない（grep確認）。`ci.yml`のコメントに将来やってもよいという記述が
    あるのみで、設計原則9（DEFERにはトリガーを付ける）に沿った追跡がされていない。
- Impact: MVTのCASE式↔domain純関数の突き合わせテスト・`edge_search_materials`関連・
  `road_graph_repository`関連など、PostGIS実DBに依存する検証（多くがこのプロジェクトの
  最も複雑で不具合が実際に出ている領域）が、T230で「CI復旧」と結論づけた後も引き続き
  CIの外側にある。2026-08-23時点でこの事実を認識せずに「CIが緑だから安全」と判断すると、
  同種の不具合を再び見逃すリスクがある。
- Root Cause: 設計判断自体（DB無しでCIを軽量に保つ）は合理的だが、対応するリスク受容が
  トリガー付きDEFERとして明文化・追跡されていない。
- Recommendation: 以下のいずれかをユーザー判断で選び、improvement-plan.mdへDEFER
  （トリガー付き）または実施タスクとして起票する。
  1. CIに`postgis/postgis`サービスコンテナを追加し`TEST_DATABASE_URL`を注入して全件実行する
     （`ci.yml`コメントが既に想定している対応、実行時間増とのトレードオフ）。
  2. 現状維持のままトリガー付きDEFERとして明文化する（トリガー例:「PostGIS依存コードの
     不具合がCI green後に本番/実機で発覚したとき」——**T224がまさにこのトリガー条件に
     該当する**ため、DEFERにする場合もその旨を記録し次回同種の発覚時は即着手とする）。
  3. 最低限の折衷案として、CIのpytestサマリに「Nスキップ」の件数をジョブサマリや
     アノテーションで可視化し、「緑=全件検証済み」という誤解を防ぐ。
- Scope: DEFER化のみならS。サービスコンテナ追加を選ぶ場合はS〜M（ci.yml変更＋実行時間実測）。
- Confidence: High（実測・grep確認済み）。

### [P2] F-2. `frontend/e2e/fixtures.ts`のルート生成モック応答が、実際の`GenerationConditions`契約から乖離している
- Problem: `e2e/fixtures.ts`の`routeGenerateResponseFixture()`が返す`conditions`オブジェクトは、
  OpenAPI生成物`GenerationConditions`の必須フィールド12件中5件
  （`car_stress_recipe`・`road_suitability_recipe`・`motor_vehicle_density_recipe`・
  `penalty_strength`・`max_average_grade_percent`）を欠いている。バックエンドが実際に返す
  レスポンスは必ずこの5件を含むため、e2eのモックは実契約と一致していない。
- Evidence:
  - `frontend/src/types/generated/openapi.json`の`GenerationConditions.required`配列
    （12件: latitude/longitude/distance_km/distance_tolerance_km/scoring_weights/
    route_preference/car_stress_recipe/road_suitability_recipe/
    motor_vehicle_density_recipe/penalty_strength/max_average_grade_percent/generated_at）。
  - `frontend/e2e/fixtures.ts:43-57`の`routeGenerateResponseFixture()`は
    `latitude/longitude/distance_km/distance_tolerance_km/scoring_weights/
    route_preference/generated_at`の7件のみを持つ`conditions`を返す。
  - T225（コミット1e7ade4）は同じ2フィールド（`penalty_strength`・
    `max_average_grade_percent`）の追加を`ComparisonPanel.test.tsx`・`routeApi.test.ts`の
    フィクスチャには反映したが（`git diff feb1805..origin/master`で確認）、
    `e2e/fixtures.ts`は対象に含めなかった。`car_stress_recipe`等3件は元々（T225以前から）
    欠けたまま。
  - `routeGenerateResponseFixture()`の戻り値に型注釈が無いため（`RouteGenerateResponse`を
    参照していない）、TypeScriptコンパイラはこの不足を検知しない。
- Impact: 現状は研究モード（`conditions`の欠落フィールドを読む`ComparisonPanel`等の経路）が
  smokeテストで有効化されていないため実害はないが、e2eの「バックエンド契約を模す」という
  前提（`fixtures.ts`冒頭コメント参照）が実際には崩れている。将来smokeテストが研究モードの
  経路をカバーするよう拡張された際、この欠落がテスト自体の信頼性を損なう形で顕在化しうる。
- Root Cause: `fixtures.ts`が生成型を参照せず素朴なオブジェクトリテラルのため、
  OpenAPIスキーマへ必須フィールドが追加されてもコンパイル時に検知されない
  （手動同期ペアだがドリフト検知の仕組みを持たない、context.md「正準定義と同期機構」の
  方針から外れる）。
- Recommendation: `routeGenerateResponseFixture()`の戻り値に
  `RouteGenerateResponse`型注釈を付け、TypeScriptに必須フィールド欠落を検知させる
  （型を通すために5フィールドを埋める）。恒久的なドリフト検知として型注釈を残すこと自体が
  対策になる。
- Scope: S（フィクスチャに5フィールド追加＋型注釈付与のみ）。
- Confidence: High（openapi.json・fixtures.ts両方をコード確認済み）。

## KEEP

- T224の回帰テスト（`test_save_graph_with_way_ids_to_replace_handles_edge_count_beyond_asyncpg_parameter_limit`）は、`=ANY(配列)`化前のコードで実際に失敗することが確認された上で追加されており
  （このセッション内で`git stash`による再現確認済み）、principles.mdが求める
  「事実として確認されたテスト」の模範例。
- T225のフロント修正（`penalty_strength: 1.0`をリクエストへ明示追加）は、
  OpenAPI必須化に対応する最小差分で、無関係な変更を含んでいない。

## REMOVE
該当なし。

## SIMPLIFY
該当なし（今回の差分規模では該当する冗長性を確認できず）。

## REFACTOR
該当なし。

## EXTEND
該当なし。

## DEFER
- F-1のCIへのPostGISサービスコンテナ追加そのものは、対応方針（上記Recommendation 1〜3）を
  ユーザーが選ぶまでDEFER。トリガー: 本Findingの記載どおり「PostGIS依存コードの不具合が
  CI green後に発覚したとき」（T224で既に1回成立）。

## Regression / Previous Findings

- 前回統合レビュー（2026-08-23_all.md）のF-3（architecture.md T11未追従）は
  `improvement-plan.md`でT227として引き続き追跡されており、紛失・誤クローズはない
  （grep確認、`### - [ ] T227. architecture.mdのT11完了を追従する`）。
- **本レビュー開始前に別途発見・修正済みの案件**（この整合性総点検のきっかけとなったもの）:
  `frontend/e2e/smoke.spec.ts`の「地図レイヤーのON/OFF切替」テストが、T165（「道路情報」→
  「道路種別」/「路面」への論理分割）・T166（「観測」グループの折りたたみ配下への格納）の
  2回のUI再構成にe2eテストが追従しておらず、CIのe2eジョブが恒常的に失敗していた。
  コミット4c7bf63で修正・CI（Run #268）で全green確認済み。本レビューのFinding 1・2は、
  この発覚をきっかけに「同種のずれが他にもないか」を広めに確認した結果である。
- `frontend/src/`内の他ファイルに旧ラベル「道路情報」への参照は残っていないことを
  grep確認済み（smoke.spec.tsのみが該当していた）。

## Overall Judgment

直近8コミット（T224・T225）自体は実装・テストの整合性が取れている。一方で、今回のセッションで
偶発的に発覆したe2eドリフトをきっかけに範囲を広げて確認したところ、**CIの「緑」が実際に
保証する範囲がユーザー・実装セッション双方の想定より狭い**（PostGIS統合テスト約100件が
CIの外側にあり、T224の回帰テスト自身もその中に含まれる）という、T230の完了判断に関わる
重要な事実が見つかった。T230自体の完了判断（CIは動いている／api-contract等4ジョブが
green）を覆すものではないが、「CI green＝全テスト検証済み」という誤解を防ぐため、
F-1をトリガー付きDEFERとして明文化することを推奨する。F-2は影響が軽微なため優先度は
下がるが、修正コストがS規模のため合わせて起票してよい。
