import type { components } from "./generated/api";

type Schemas = components["schemas"];

export type WeatherConditions = Schemas["WeatherConditions"];
// 「今日」のパネルの一定間隔のコマ（today_periods）1つぶん。
export type WeatherPeriodOutlook = Schemas["WeatherPeriodOutlook"];
// 応答の生の形（時刻の列を格子に1本だけ持つ）。`services/weatherApi.ts: withTimes`が`WindGridPoint`へ直す。
export type WindGridResponse = Schemas["WindGridResponse"];
// 画面が使う格子点。点ごとにtimesを持つのは、取った時刻が違う点（前回の値で補った点）が1つの格子に同居し、
// 時刻の列の先頭がそれぞれ違うため（値は点ごとに時刻で引く。windLayer.ts: timeIndexOf）。
export type WindGridPoint = Schemas["WindGridPoint"] & { times: WindGridResponse["times"] };
// 最寄りのアメダス観測所の実測値。
export type AmedasObservation = Schemas["AmedasObservation"];
// 警報・注意報、暑さ指数、河川氾濫予報。空の中身は「出ていない」を表す。
export type WeatherWarnings = Schemas["WeatherWarnings"];
export type WbgtStatus = Schemas["WbgtStatus"];
export type FloodForecasts = Schemas["FloodForecasts"];
