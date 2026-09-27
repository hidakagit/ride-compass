// backendのOpenAPIスキーマから生成した generated/api.d.ts の再エクスポート
// （経緯・更新手順は types/route.ts のコメント参照）。
import type { components } from "./generated/api";

export type WeatherConditions = components["schemas"]["WeatherConditions"];
// 「今日」のパネルの2時間おきのコマ（today_periods）1つぶん。
export type WeatherPeriodOutlook = components["schemas"]["WeatherPeriodOutlook"];
// バックエンドの応答本体（時刻配列を1本だけ持つ）。weatherApi.tsの
// getWindGrid/getWindGridDetailが受け取る生の形で、フロント内部では使わない
// （services/weatherApi.ts参照）。
export type WindGridResponse = components["schemas"]["WindGridResponse"];
// フロント内部で使う格子点の表現。バックエンドのWindGridPoint（times無し）に、
// 応答トップレベルのtimesを合成したもの（services/weatherApi.ts: getWindGridPoints）。
// 点ごとにtimesを持つのは、取った時刻が違う点（前回の値で補った点）が1つの格子に同居し、
// 時刻の列の先頭がそれぞれ違うため（値は点ごとに時刻で引く。windLayer.ts: timeIndexOf）。
// ネットワーク上の表現とフロント内部表現をここで切り離すことで、応答サイズ削減が
// 内部ロジックへ波及しないようにしている。
export type WindGridPoint = components["schemas"]["WindGridPoint"] & { times: string[] };
export type WeatherWarnings = components["schemas"]["WeatherWarnings"];
export type WbgtStatus = components["schemas"]["WbgtStatus"];
export type FloodForecasts = components["schemas"]["FloodForecasts"];
// 最寄りアメダス観測所の実測値。常設ヘッダー（WeatherPanel）が使う。
export type AmedasObservation = components["schemas"]["AmedasObservation"];
