# RideCompass

サイクリング向け周回ルート生成アプリ。backend（FastAPI）+ frontend（Next.js）。
アーキテクチャ全体は docs/architecture.md 参照。

設計レビュー（2026-08-15〜16）の指摘と改善実行計画は docs/improvement-plan.md にある。
リファクタリング・機能追加の着手前に該当タスクの有無を確認し、完了したらチェックを更新すること。
設計原則10箇条は docs/design-review-2026-08-15.md 末尾を参照。複雑度平衡の追加原則
（評価軸追加の1本道・定数の片側import・UI語彙のカタログ集約等）は
docs/complexity-review-2026-08-16.md 末尾の改訂版が最新。

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
- PostGIS統合テスト（road_graph_session、conftest.py）はファイル単位でエンジン・イベントループを共有する設計。新規ファイルでは `pytestmark = pytest.mark.asyncio(loop_scope="module")` が必要（自前の追加async fixtureにも `loop_scope="module"` を明示）
- フロントエンドの新規テストがDOM（render/renderHook/window等）を使わない純ロジックなら、vitest.config.mts の environmentMatchGlobs への追加を検討する
