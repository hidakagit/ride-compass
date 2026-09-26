import type { ReactElement } from "react";
import { MoonIcon, SunIcon } from "@/components/ui/icons/icons";

import { WEATHER_CATEGORY_ICON, WEATHER_CATEGORY_LABEL, weatherCategoryOf } from "./weatherCode";

interface AmedasWeatherDisplay {
  Icon: (props: { size?: number }) => ReactElement;
  label: string;
}

/** アメダスの実測からbackendが導いた天気コード+昼夜フラグから天気アイコン+ラベルを決める
 * （weatherCode.tsのgetWeatherCodeDisplayと同じ構成）。コードが無ければnullを返す。 */
export function getAmedasWeatherDisplay(weatherCode: number | null, isDay: boolean): AmedasWeatherDisplay | null {
  if (weatherCode == null) return null;
  const category = weatherCategoryOf(weatherCode);
  const label = WEATHER_CATEGORY_LABEL[category];
  // 「晴れ」だけは実測のis_dayで昼夜を切り替える（アメダスはコマ単位の昼夜を持つ）。
  if (category === "clear") {
    return { Icon: isDay ? SunIcon : MoonIcon, label };
  }
  return { Icon: WEATHER_CATEGORY_ICON[category], label };
}
