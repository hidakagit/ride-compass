// backendのOpenAPIスキーマから生成した generated/api.d.ts の再エクスポート
// （経緯・更新手順は types/route.ts のコメント参照）。
import type { components } from "./generated/api";

export type WeatherConditions = components["schemas"]["WeatherConditions"];
// 「今日の見通し」パネルの天気の流れ（today_periods、改善計画T385フォローアップ）1コマぶん。
export type WeatherPeriodOutlook = components["schemas"]["WeatherPeriodOutlook"];
// バックエンドの応答本体（改善計画T203、時刻配列を1本だけ持つ）。weatherApi.tsの
// getWindGrid/getWindGridDetailが受け取る生の形で、フロント内部では使わない
// （services/weatherApi.ts参照）。
export type WindGridResponse = components["schemas"]["WindGridResponse"];
// フロント内部で使う格子点の表現。バックエンドのWindGridPoint（times無し）に、
// 応答トップレベルのtimesを合成したもの（weatherApi.ts: toWindGridPoints）。
// windLayer.ts・useWeatherGrid.ts等の内部ロジックは「各点がtimesを持つ」前提のまま
// 変えていない（trimWindGridToCurrentAndFuture等が個々の点のtimesをスライスする設計、
// ネットワーク上の表現とフロント内部表現をここで切り離すことで、T203の応答サイズ削減が
// 内部ロジックへ波及しないようにしている）。
export type WindGridPoint = components["schemas"]["WindGridPoint"] & { times: string[] };
export type WeatherWarnings = components["schemas"]["WeatherWarnings"];
export type ActiveWarning = components["schemas"]["ActiveWarning"];
export type WbgtStatus = components["schemas"]["WbgtStatus"];
export type FloodForecasts = components["schemas"]["FloodForecasts"];
export type ActiveFloodForecast = components["schemas"]["ActiveFloodForecast"];
// 最寄りアメダス観測所の実測値（改善計画T387フォローアップ）。常設ヘッダー（WeatherPanel）が使う。
export type AmedasObservation = components["schemas"]["AmedasObservation"];
