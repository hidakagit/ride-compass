# RideCompass

サイクリング向け周回ルート生成アプリ。backend（FastAPI）+ frontend（Next.js）。
アーキテクチャ全体は docs/architecture.md 参照。

設計レビュー（2026-08-15）の指摘と改善実行計画は docs/improvement-plan.md にある。
リファクタリング・機能追加の着手前に該当タスクの有無を確認し、完了したらチェックを更新すること。
設計原則10箇条は docs/design-review-2026-08-15.md 末尾を参照。

## ログ方針（必読）

**コードを追加・変更するときは docs/logging.md のログ方針に従うこと。** 要点:

- エラー・429拒否・候補0件はWARNING以上で**常時**出す（debug_modeはDEBUG詳細の追加スイッチであり、エラー出力の条件にしない）
- 外部API/キャッシュアクセスは `app/infrastructure/debug_log.py` の `log_external_call` で囲む（cache hit/miss・result・statusをfieldsに設定。ログと /api/debug/stats の統計が自動で付く）
- 高コスト処理はステージ別所要時間と中間結果の減り方を1行INFOサマリにする（route_generator.py参照）
- リクエストIDは request_log.py のミドルウェアが全ログへ自動付与する。個別ログに書かない
- 常時出るログの座標は小数2桁へ丸める。APIキーはどのレベルでも出さない
