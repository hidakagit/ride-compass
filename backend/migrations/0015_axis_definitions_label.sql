-- 改善計画T269（軸カタログのDB追従、目論見書「二画面構想」Phase 2前提）。
-- ADR: docs/decisions/t221-axis-registry.md。
--
-- 0014で作ったaxis_definitionsテーブルへ表示名（label/description/category）を追加する。
-- domain/axis_definitions.pyのAxisDefinitionへ同じ3フィールドを追加済み。NOT NULL DEFAULTで
-- 追加するため、0014が既に本番へ適用済みでも安全（既存7行はこのmigration内のUPDATEで
-- 実際の値へbackfillし、以降の新規行はAxisRegistryAdminService経由で必ず明示的に
-- 値が入る。DEFAULTは「予期せず素通りしたNOT NULL違反」を防ぐ保険）。
-- 未適用の環境ではservices/axis_registry_service.pyが従来どおりWARNINGログを出しつつ
-- domain/axis_definitions.py内蔵の既定値へ安全側フォールバックするため、本migrationを
-- 本番へ適用するまでの間は評価の振る舞い・表示のいずれも変わらない（T74の教訓を踏まえた
-- 意図的な安全側ロールアウト、0014と同じ方針）。
ALTER TABLE axis_definitions
    ADD COLUMN IF NOT EXISTS label TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS description TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS category TEXT NOT NULL DEFAULT '推定';

-- 既存7軸のlabel/description/categoryをdomain/axis_definitions.pyのAXIS_DEFINITIONSから
-- そのまま複製する（0014と同じ「挙動・表示が変わらないことがStage移行の前提」原則）。
UPDATE axis_definitions SET label = '勾配', description = '登り坂の急さが小さいほど易しい', category = '観測' WHERE axis_id = 'gradient';
UPDATE axis_definitions SET label = '風', description = '向かい風が弱いほど易しい', category = '動的' WHERE axis_id = 'wind';
UPDATE axis_definitions SET label = '舗装質', description = '舗装路であるほど易しい', category = '観測' WHERE axis_id = 'surface_q';
UPDATE axis_definitions SET label = '停止密度', description = '信号・横断歩道・一時停止・踏切・交差点(次数3以上の分岐点、低い重み)が少ないほど易しい', category = '観測' WHERE axis_id = 'stop_density';
UPDATE axis_definitions SET label = '車の圧迫感', description = '推定される車の圧迫感(1-5)が低いほど易しい。自動車との近さ・速さ・車線数・自転車インフラの指標で、信号や交差点の頻度は含まない(別軸)', category = '推定' WHERE axis_id = 'car_stress';
UPDATE axis_definitions SET label = '事故密度', description = '事故密度(件/(km・年)、警察庁統計)が低いほど易しい', category = '推定' WHERE axis_id = 'accident';
UPDATE axis_definitions SET label = '夜間', description = '街灯なし・トンネルが少ないほど易しい。既定重み0(夜間ライドを重視する場合に個別に上げる想定)', category = '観測' WHERE axis_id = 'night';
