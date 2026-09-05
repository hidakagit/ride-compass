import type { ReactElement } from "react";
import { CloudIcon, MoonIcon, RaindropIcon, SnowflakeIcon, SunIcon } from "@/components/Map/icons";

// 常設ヘッダーの天気アイコンはOpen-Meteoのweather_code（予報由来）ではなく
// アメダス実測値ベースの簡易分類を使う。weatherCode.ts（Open-Meteo、6カテゴリ）と
// 違い、アメダスの速報値レスポンスには天気概況コードが実質使えない形でしか無い
// （新設フィールドsunshine_10min_minutes[10分間日照時間]・precipitation_10min_mm
// [10分間降水量]・temperature_cのみを根拠にする）ため、霧・雷雨は判別できず
// 4カテゴリ（晴れ/くもり/雨/雪）に留める。
export type AmedasWeatherCategory = "clear" | "cloudy" | "rain" | "snow";

// 降水がある場合に雨/雪を分ける気温しきい値（℃）。気象庁の目安（地上気温2℃前後が
// 雨/雪の境目）に基づく簡易な近似——みぞれ等の中間状態は判別しない。
const SNOW_TEMPERATURE_THRESHOLD_C = 2;

/** アメダスの生値から天気カテゴリを判定する。降水量・日照時間のいずれも無ければ
 * 判定材料が無いためnullを返す（呼び出し元はチップ自体を出さない）。 */
export function classifyAmedasWeather(
  precipitation10minMm: number | null,
  sunshine10minMinutes: number | null,
  temperatureC: number | null,
): AmedasWeatherCategory | null {
  if (precipitation10minMm != null && precipitation10minMm > 0) {
    return temperatureC != null && temperatureC <= SNOW_TEMPERATURE_THRESHOLD_C ? "snow" : "rain";
  }
  if (sunshine10minMinutes != null) {
    return sunshine10minMinutes > 0 ? "clear" : "cloudy";
  }
  return null;
}

const CATEGORY_LABEL: Record<AmedasWeatherCategory, string> = {
  clear: "晴れ",
  cloudy: "くもり",
  rain: "雨",
  snow: "雪",
};

const ICON_BY_CATEGORY: Record<Exclude<AmedasWeatherCategory, "clear">, (props: { size?: number }) => ReactElement> = {
  cloudy: CloudIcon,
  rain: RaindropIcon,
  snow: SnowflakeIcon,
};

export interface AmedasWeatherDisplay {
  Icon: (props: { size?: number }) => ReactElement;
  label: string;
}

/** カテゴリ+昼夜フラグから天気アイコン+ラベルを決める（weatherCode.tsのgetWeatherCodeDisplay
 * と同じ構成）。category=nullの場合はnullを返す。 */
export function getAmedasWeatherDisplay(category: AmedasWeatherCategory | null, isDay: boolean): AmedasWeatherDisplay | null {
  if (category == null) return null;
  const label = CATEGORY_LABEL[category];
  if (category === "clear") {
    return { Icon: isDay ? SunIcon : MoonIcon, label };
  }
  return { Icon: ICON_BY_CATEGORY[category], label };
}
