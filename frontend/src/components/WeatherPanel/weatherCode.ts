import type { ReactElement } from "react";
import { CloudIcon, FogIcon, RaindropIcon, SnowflakeIcon, SunIcon, ThunderIcon } from "@/components/Map/icons";

// WMO天気コード（weather_code、backendが降水量・雲量・気温から導出）+ is_dayから、
// 「今日の見通し」（TodayOutlook）の天気アイコン1個を決める。実測値ベースの常設ヘッダーは
// 別の簡易分類を使う（amedasWeatherIcon.ts）。
//
// WMOコードの全パターンを個別に描き分けるのではなく、天候ヘッダーの小さい1アイコンに
// 収まる粒度（6カテゴリ）へ意図的に粗く丸める（「晴れ時々くもり」等の細かい中間状態は
// アイコンでは判別困難で、かえって視認性を落とすため）。
export type WeatherCodeCategory = "clear" | "cloudy" | "fog" | "rain" | "snow" | "thunderstorm";

// backendが実際に返すのは雲量・雨・雪の段階に対応するコードだけ（domain/weather.py:
// derive_weather_codeが正本。霧・雷雨はMSMの配信変数から判定できないため返さない）。
// 残りはWMO標準の対応表としてそのまま持つ——導出ロジックが変わって新しいコードが返る
// ようになったとき、未知コードのフォールバック（下の`?? "cloudy"`）で雨や雪まで
// くもり扱いになるのを避けるため。
const CATEGORY_BY_CODE: Record<number, WeatherCodeCategory> = {
  0: "clear",
  1: "clear",
  2: "cloudy",
  3: "cloudy",
  45: "fog",
  48: "fog",
  51: "rain",
  53: "rain",
  55: "rain",
  56: "rain",
  57: "rain",
  61: "rain",
  63: "rain",
  65: "rain",
  66: "rain",
  67: "rain",
  71: "snow",
  73: "snow",
  75: "snow",
  77: "snow",
  80: "rain",
  81: "rain",
  82: "rain",
  85: "snow",
  86: "snow",
  95: "thunderstorm",
  96: "thunderstorm",
  99: "thunderstorm",
};

// 天気カテゴリの語彙とアイコンの**単一の情報源**。ヘッダー（アメダス実測）と真下の
// 「今日の見通し」（MSM予報）が同じアイコンに別の語を出さないよう、両方がここを読む
// （`amedasWeatherIcon.ts`はアメダスが扱う4カテゴリだけを使い、昼夜の切り替えだけを足す）。
export const WEATHER_CATEGORY_LABEL: Record<WeatherCodeCategory, string> = {
  clear: "晴れ",
  cloudy: "くもり",
  fog: "霧",
  rain: "雨",
  snow: "雪",
  thunderstorm: "雷雨",
};

// 「晴れ」以外は昼夜で見た目を変えない（くもり・雨・雪・霧・雷雨は昼夜どちらでも同じ
// アイコンで十分伝わり、6カテゴリ×2でアイコン数を倍にするほどの価値が無いため）。
export const WEATHER_CATEGORY_ICON: Record<WeatherCodeCategory, (props: { size?: number }) => ReactElement> = {
  clear: SunIcon,
  cloudy: CloudIcon,
  fog: FogIcon,
  rain: RaindropIcon,
  snow: SnowflakeIcon,
  thunderstorm: ThunderIcon,
};

export interface WeatherCodeDisplay {
  Icon: (props: { size?: number }) => ReactElement;
  label: string;
}

/** weather_codeから天気アイコン+ラベルを決める。weather_codeが無い（null）場合は
 * 何も表示すべきでないためnullを返す（呼び出し元はチップ自体を出さない）。
 *
 * 昼夜でアイコンを変えない。呼び出し元（TodayOutlook）はコマ単位のis_dayを持たないため
 * （観測側で昼夜を持つのは`amedasWeatherIcon.ts`）。 */
export function getWeatherCodeDisplay(weatherCode: number | null): WeatherCodeDisplay | null {
  if (weatherCode == null) return null;
  const category = CATEGORY_BY_CODE[weatherCode] ?? "cloudy";
  return { Icon: WEATHER_CATEGORY_ICON[category], label: WEATHER_CATEGORY_LABEL[category] };
}
