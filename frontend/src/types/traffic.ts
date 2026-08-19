// backendのOpenAPIスキーマから生成した generated/api.d.ts の再エクスポート
// （経緯・更新手順は types/route.ts のコメント参照）。
import type { components } from "./generated/api";

export type CarStressBreakdown = components["schemas"]["CarStressBreakdown"];
// 区間インスペクタ（改善計画T146）。
export type AxisInspectorAxis = components["schemas"]["AxisInspectorAxis"];
export type AxisInspectorResult = components["schemas"]["AxisInspectorResult"];
