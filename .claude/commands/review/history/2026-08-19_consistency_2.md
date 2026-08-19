# 設計・実装・テスト整合性レビュー（2026-08-19・2回目）

- 実施日: 2026-08-19
- レビュー種別: consistency
- 対象コミット（HEAD固定）: `7681611730abbc3e3cd88bdd091cee02d3d78530`
- 前回同種レビュー: [2026-08-19_all.md](2026-08-19_all.md) Phase 4（対象コミット`e90d920`）、
  [2026-08-17_consistency.md](2026-08-17_consistency.md)
- 対象範囲: `e90d920..7681611`（21コミット。統合レビュー2026-08-19の起票T153〜T160の実施＋
  改善計画の棚卸し整理＋並行セッションによるT148「旧・安全度レイヤーと計算コードを削除」）
- 実施場所: 専用worktree（`/tmp/.../scratchpad/consistency-worktree`、HEAD固定・detached）。
  本体の作業ツリーは調査中一切変更していない。

## 対象範囲についての注記

ユーザー指定は「全般コミットについて確認して」。前回同種レビュー（2026-08-19_all.md Phase 4）
の対象コミット`e90d920`以降、21コミットが積まれている。うち実質的な変更は
T148（並行セッション、旧安全度レイヤー一括削除）と、前回統合レビューの起票T153〜T160
（本セッションが実施、T158・T159は対象消滅によりクローズ）。docs系コミット（レビュー結果保存・
改善計画棚卸し整理）も対象に含めた。

## Executive Summary

T153〜T157・T160はいずれも実装・テスト・docsの整合性が高い水準で保たれていることを確認した。
OpenAPI・生成物9種・フロント型は`export_openapi.py`・`generate:api`を実際に再実行し差分ゼロを
実測、backend pytest 815件・frontend vitest 340件・eslint・tscすべてgreen。T148
（並行セッション）についても、削除対象のシンボル・エンドポイント・レイヤーがコードベースから
実際に消えていること、DB migration・タイル世代への影響が無い（安全度はDB/タイルに永続化
されていなかったため）ことをコードで確認した。

一方、3件の軽微な残存ギャップを検出した。最も実務上意味があるのは、T146（区間インスペクタ）
実装前後の呼び出し順序を`git log`で確認する過程で、`frontend/src/components/Map/
recipeExpression.ts`のコメントがT148で削除済みの`SAFETY_COLOR_EXPRESSION`をあたかも
現存するかのように記述している点（P3）。残り2件は、前回レビュー起票分（T156）自身が
意図的にスコープを絞った際の残存ギャップと、レビュー履歴ファイル自身の「対応状況」欄の
更新漏れで、いずれも実害は無いが記録しておく。P0/P1は無し。

## Findings

### [P3] F-1. `recipeExpression.ts`のコメントがT148で削除済みの`SAFETY_COLOR_EXPRESSION`を現存するシンボルとして記述している

- Problem: `frontend/src/components/Map/recipeExpression.ts:20`のコメントが
  「既存のCAR_STRESS_COLOR_EXPRESSION/SAFETY_COLOR_EXPRESSIONが`coalesce(*, -1)`で
  使っていたのと同じ値・同じ意味に揃える」と記述しているが、`SAFETY_COLOR_EXPRESSION`は
  T148（`safetyExpression.ts`ごと削除）で既に存在しない。`CAR_STRESS_COLOR_EXPRESSION`
  （`staticAttributeLayers.ts:155`）は現存する。
- Evidence: `grep -rn "SAFETY_COLOR_EXPRESSION" frontend/src`は`recipeExpression.ts:20`の
  コメント記述のみがヒットし、実体の定義・importはどこにも存在しない
  （`safetyExpression.ts`自体がT148の削除対象、`git show 6b7a2e7 --stat`で確認済み）。
- Impact: 実害なし（コメントのみ、コンパイル・実行に影響しない）。ただし次にこのファイルを
  読む開発者が「安全度の色分けexpressionが別途どこかに存在する」と誤解するリスク。
- Root Cause: T148の削除範囲が`safetyExpression.ts`本体・テスト・型定義には及んだが、
  それを参照する側の他ファイルのコメントまでは網羅的にgrepされなかった
  （T148実装メモにコメント修正への言及なし）。
- Recommendation: コメントを「既存のCAR_STRESS_COLOR_EXPRESSIONが`coalesce(*, -1)`で
  使っていたのと同じ値・同じ意味に揃える（旧SAFETY_COLOR_EXPRESSIONも同じ規約だったが
  T148で削除済み）」等、現状に合わせて1行修正する。
- Scope: S / Confidence: High / 乖離の分類: 実装（コメント）↔実装（削除済みシンボル）

### [P3] F-2. `_AXIS_DIFFICULTY_FIELD_TO_AXIS_ID`自体はT156のドリフト検知テストの対象外のまま残っている

- Problem: T156（本レビュー対象範囲、`592a3b1`）が追加した
  `test_registry_axis_ids_match_evaluation_axis_weight_mapping`は
  `AXIS_WEIGHT_FIELD_TO_AXIS_ID`とレジストリの軸ID集合の一致のみを検証し、
  同じ役割を持つもう一方の手書き辞書`_AXIS_DIFFICULTY_FIELD_TO_AXIS_ID`
  （`compute_edge_axis_scores`が使う）はテスト対象に含まれていない。
- Evidence: `backend/app/domain/evaluation.py:95-113`に両辞書が隣接定義されており、
  現状は値集合が完全一致（`{gradient, wind, surface_q, stop_density, car_stress, accident,
  night}`）していることを確認したが、これを検証するテストは無い
  （`grep -rn "_AXIS_DIFFICULTY_FIELD_TO_AXIS_ID" backend/tests`は0件）。
  T156自身の実装メモ（`docs/improvement-plan.md`）は「キーの集合が常に同じ形で保守されており
  実用上十分なため後者のみ対象とした」と明記しており、意図的なスコープ限定であることは
  記録済み。
- Impact: 軽微。`_AXIS_DIFFICULTY_FIELD_TO_AXIS_ID`だけを単独で誤編集した場合
  （`AXIS_WEIGHT_FIELD_TO_AXIS_ID`は正しいまま）、T156のテストは気づかない。
  ただし両辞書は`evaluation.py`内の隣接する13行に収まっており、実際の編集時に片方だけ
  触れるミスの可能性は低い。
- Root Cause: T156の対応方針が「1行アサーション」というスコープSの規模感で立てられており、
  2つ目の辞書までは当初のRecommendationに含まれていなかった（統合レビュー2026-08-19
  complexity F-2の原文も`AXIS_WEIGHT_FIELD_TO_AXIS_ID`のみを名指ししていた）。
- Recommendation: 対応するかはユーザー判断。対応する場合は同テストへ
  `set(_AXIS_DIFFICULTY_FIELD_TO_AXIS_ID.values()) == registry_axis_ids`の1行を追加する
  （追加コストは小さい）。
- Scope: S / Confidence: High / 乖離の分類: 実装↔テスト

### [P3/情報] F-3. レビュー履歴`2026-08-19_all.md`の「対応状況」欄が「実施はまだ」のまま更新されていない

- Problem: `.claude/commands/review/history/2026-08-19_all.md`末尾の「対応状況」節が
  「T153〜T160として起票済み...実施はまだ（起票のみ）」のままだが、対象範囲コミット
  （T153・T154・T155・T156・T157・T160）は本レビュー時点で全て実装完了、T158・T159は
  対象消滅によりクローズ済み。
- Evidence: `docs/improvement-plan.md`のT153・T154・T155・T156・T157・T160はいずれも
  `[x]`＋完了日・実装メモつき。T158・T159も`[x]`＋「対象消滅により対応不要」の実装メモつき。
  一方`2026-08-19_all.md`の該当節は起票直後の文言のまま。
- Impact: 実害なし（`docs/improvement-plan.md`側が正であり、そちらを見れば実態は追える）。
  ただし`history/README.md`が「対応状況欄の更新のみ許可」と明記している運用にこのファイル
  自身が追従できていない。
- Recommendation: 「対応状況」欄を「統合-1〜8: T153〜T160として起票・実施完了
  （T158・T159は並行セッションのT148完了により対象消滅、対応不要としてクローズ）」等へ
  更新する。history/README.mdが明示的に許可する更新のため、本レビューの起票案としてではなく
  単純な追記提案として扱う。
- Scope: S / Confidence: High / 乖離の分類: レビュー履歴の状態欄↔実態

## KEEP（変更しない方がよい設計。確認して問題なしだった箇所）

- **T148の削除範囲の完全性**: `domain/safety.py`・`safety_recipe.yaml`・
  `SafetyRecipeOverride`・`safetyExpression.ts`・`SafetyRecipePanel/`・
  `POST /api/region/safety-breakdown`がコードベースから実際に消えていることをgrepで確認
  （残存する`safety`文字列は全て「T148で削除済み」と説明する履歴コメント、または
  意図的に維持されている`category="trafficSafety"`UIカテゴリ定数のみ）。
- **T148がDB/タイルへ影響しないこと**: `git show 6b7a2e7 --stat`で`backend/migrations/`・
  `road_graph_models.py`・`road_graph_repository.py`のいずれも変更対象に含まれていないことを
  確認。安全度は元々DB永続化・MVTタイル焼き込みの対象ではなかったため、
  `ROAD_SURFACE_TILE_VERSION`（現在"12"のまま）の対上げは不要かつ実際に不要と判断されている。
- **T146（区間インスペクタ）とT148の整合**: `axis_inspector_breakdown`
  （`domain/evaluation.py:153-`）は現状5軸（car_stress/surface_q/stop_density/accident/night）
  のみを算出しており、安全度への参照は元から存在しない（T146はT139のsafety軸廃止より後に
  実装されたため）。T148のdiffもこの関数へは触れていない。
- **OpenAPI・生成物・フロント型の同期**: `export_openapi.py`・`npm run generate:api`を
  実際に再実行し、9種の生成物（`openapi.json`・`surface-tags.json`・
  `region-tile-config.json`・`axis-catalog.json`等）・`api.d.ts`いずれも差分ゼロを実測。
- **T153・T156の回帰テストの実効性**: いずれも実装メモに「フィックスを一時的に外して
  実際にfailすることを確認した」旨が記録されており、本レビューでもコード上の実装
  （`car_stress_level_value`引数・`register_axis`突き合わせ）と回帰テストの対応関係を
  突き合わせて矛盾がないことを確認した。
- **T155（recipe_definition.py削除）の完全性**: `grep -rln "recipe_definition" backend`が
  0件であることを確認（ファイル・テスト・importいずれも残存なし）。
- **improvement-plan.md棚卸し整理後のT番号完全性**: 本体＋アーカイブ4ファイルを通じて
  T番号の重複・欠落が無いことを機械的に確認（`sort | uniq -c`で全て1件）。相対リンクも
  全て解決することを確認。

## REMOVE
該当なし。

## SIMPLIFY
該当なし。

## REFACTOR
該当なし。

## EXTEND
- F-2の対応（`_AXIS_DIFFICULTY_FIELD_TO_AXIS_ID`もドリフト検知テストへ含める）。ユーザー判断。

## DEFER
該当なし（F-1〜F-3はいずれもS規模で即対応可能なため、DEFERへ回す理由がない）。

## Regression / Previous Findings

| 前回（2026-08-19_all.md Phase4） | 状態 |
|---|---|
| F-1（P1、`base_by_highway`独立の誤記述） | **解消確認**。T154で実装に合わせ修正済み（`docs/architecture.md`の該当段落を直接確認） |
| F-2（P1、T146区間インスペクタ未反映） | **解消確認**。T154で§4・§7へ追記済み |
| F-3（P2、レジストリ機構`registry.py`未説明） | **解消確認**。T154で§7に専用小節を新設済み |
| F-4（P3、`RouteSegmentDetail`旧フィールド列挙） | **解消確認**。T154で現行7指標へ更新済み |
| F-5（情報、テスト環境メモ） | 参考記録のため対応不要、変化なし |

| 2026-08-17_consistency.md | 状態 |
|---|---|
| P1（T92タイル世代対上げ漏れ） | 再発なし。今回範囲でタイル世代変更自体が発生していない（T148はタイル非関与） |
| P2（ログ方針の局所的不徹底） | 再発なし。今回範囲の新規コードは全てログ方針に非該当（純関数・削除・テストのみ） |

**双子実装の対称性チェック（context.mdの削除条件付き項目）について**: T148により
「車ストレス⇔安全度」という双子の一方（安全度）自体が完全に削除されたため、この特定の
双子ペアに関する対称性チェックはもはや対象が存在しない。ただし、統合レビュー2026-08-19の
overall F-1（`car_closeness()`の二重計算がT143経由で再発、T153で解消）がこのプロジェクトで
3回目に続く4回目の同型パターンだったことを踏まえると、「双子実装の対称性」という観点自体
（片方だけ直して別の箇所を忘れる）は、車ストレス⇔安全度という具体的なペアが消えた後も、
一般的なチェック観点としては引き続き有効と判断する。基準ファイルの書き換えは本レビューの
範囲外のため、`/review:improve`での提案に委ねる。

## Overall Judgment

T148・T153〜T157・T160のいずれも、「設計→実装→テスト」の一致という観点では高品質だった。
特にT148（大規模な機能削除）は削除漏れ・DB/タイルへの意図しない影響のいずれも無く、
削除系コミットとして模範的だった。T153・T156は自身の回帰テストが実際に検知能力を持つことを
実装時に検証しており、レビュー時の再確認でも矛盾は見つからなかった。

検出した3件（F-1〜F-3）はいずれもP3・規模Sで、実害はほぼ無い軽微な取りこぼしである。
F-1（削除済みシンボルへの言及コメント）はT148の削除範囲が「参照する側のコメント」までは
機械的にgrepされなかったことに起因し、F-2はT156自身が対応方針の時点でスコープを意図的に
絞ったことの記録済みの帰結、F-3はレビュー運用（対応状況欄の更新）の単純な追従漏れである。
いずれも次にこれらのファイルへ触れる際に「ついで」で直せる規模であり、単独タスクとして
急いで起票する必要性は低いと判断する。

---

## 起票案（ユーザー承認後にimprovement-plan.mdへ起票）

P0/P1は無し。P3として以下を一括の軽微修正タスクとして起票することを提案する（急ぎではない）。

1. **【P3】recipeExpression.tsのコメントから削除済みSAFETY_COLOR_EXPRESSIONへの言及を修正**
   （F-1）: 規模S。
2. **【P3】_AXIS_DIFFICULTY_FIELD_TO_AXIS_IDもT156のドリフト検知テストへ含める**（F-2）:
   規模S。対応要否はユーザー判断（現状のリスクは小さい）。
3. **【P3/情報】history/2026-08-19_all.mdの「対応状況」欄を実施完了の内容へ更新**（F-3）:
   規模S。history/README.mdが明示的に許可する更新のため、起票を経ずに直接更新してもよい
   （ユーザー判断）。

## 対応状況
- 本レビューの指摘（F-1〜F-3）は未対応（起票案のまま、ユーザー承認待ち）。
