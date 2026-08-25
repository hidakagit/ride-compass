-- 改善計画T271（軸の公開フローと統治ルール、Phase 3）。
-- ADR: docs/decisions/t221-axis-registry.md。
--
-- axis_definitionsテーブルへ公開状態（is_published）を追加する。domain/axis_definitions.py:
-- AxisDefinitionへ同じフィールドを追加済み（既定False=下書き）。一般ユーザーの保存設定
-- （RouteSettingsPanelのプリセット・重み）はaxis_idキーで再現されるため、公開済み軸への
-- 破壊的変更・削除はAxisRegistryAdminServiceが拒否する（check_publish_immutability）。
--
-- 既存7行（本番稼働中、いずれも一般ユーザーへ既に公開済み）は
-- DEFAULT trueでbackfillされる（0014/0015と同じ「既存の挙動・表示が変わらないことが
-- Stage移行の前提」原則）。以降の新規行（軸スタジオ経由の作成）はAxisRegistryAdminService/
-- domain/axis_definitions.pyの既定False（下書き）が明示的に入るため、DEFAULT trueは
-- 移行時のbackfillのみに働く一時的な安全弁（予期せず素通りしたNOT NULL違反を防ぐ保険）。
--
-- 未適用の環境ではservices/axis_registry_service.pyが従来どおりWARNINGログを出しつつ
-- domain/axis_definitions.py内蔵の既定値（is_published=True、既存7軸分）へ安全側
-- フォールバックするため、本migrationを本番へ適用するまでの間は評価の振る舞い・表示の
-- いずれも変わらない。
ALTER TABLE axis_definitions
    ADD COLUMN IF NOT EXISTS is_published BOOLEAN NOT NULL DEFAULT true;
