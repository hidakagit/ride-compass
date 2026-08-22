// backendのOpenAPIスキーマから生成した generated/api.d.ts の再エクスポート
// （経緯・更新手順は types/route.ts のコメント参照）。
import type { components } from "./generated/api";

export type WeatherConditions = components["schemas"]["WeatherConditions"];
export type WindGridPoint = components["schemas"]["WindGridPoint"];
export type WeatherWarnings = components["schemas"]["WeatherWarnings"];
export type ActiveWarning = components["schemas"]["ActiveWarning"];
export type WbgtStatus = components["schemas"]["WbgtStatus"];
