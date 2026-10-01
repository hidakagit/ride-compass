import type { ReactElement } from "react";
import { MoonIcon, SunIcon } from "@/components/ui/icons/icons";

import { WEATHER_CATEGORY_ICON, WEATHER_CATEGORY_LABEL, weatherCategoryOf } from "./weatherCode";

interface AmedasWeatherDisplay {
  Icon: (props: { size?: number }) => ReactElement;
  label: string;
}

/** アメダスの実測からbackendが導いた天気コード+昼夜フラグから天気アイコン+ラベルを決める。
 * コードが無い・分類に無ければnullを返す。 */
export function getAmedasWeatherDisplay(weatherCode: number | null, isDay: boolean): AmedasWeatherDisplay | null {
  if (weatherCode == null) return null;
  const category = weatherCategoryOf(weatherCode);
  if (category === null) return null;
  const label = WEATHER_CATEGORY_LABEL[category];
  // 「晴れ」だけは昼夜でアイコンを切り替える（昼夜は呼ぶ側が観測地点の日の出・日没から決める）。
  if (category === "clear") {
    return { Icon: isDay ? SunIcon : MoonIcon, label };
  }
  return { Icon: WEATHER_CATEGORY_ICON[category], label };
}
