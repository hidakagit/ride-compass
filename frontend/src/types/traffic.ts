// backendのOpenAPIスキーマから生成した generated/api.d.ts の再エクスポート
// （経緯・更新手順は types/route.ts のコメント参照）。
import type { components } from "./generated/api";

// 改善計画T292: CarStressBreakdown（旧車ストレス専用内訳）はbackend側で専用Pythonレシピ
// ごと廃止し、区間インスペクタ（下記）へ統合したため型定義も削除した。
// 区間インスペクタ（改善計画T146）。
export type AxisInspectorAxis = components["schemas"]["AxisInspectorAxis"];
export type AxisInspectorResult = components["schemas"]["AxisInspectorResult"];
