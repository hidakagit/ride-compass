import type { ReactElement } from "react";
import { vocabulary } from "@/types/generated/vocabulary";
import { CloudIcon, FogIcon, RaindropIcon, SnowflakeIcon, SunIcon, ThunderIcon } from "@/components/ui/icons/icons";

// WMO天気コード（weather_code。予報も観測もbackendが導出する）から天気アイコン1個を決める。
// 天気コードの分類と名前はbackendの宣言（domain/weather_display.py: WEATHER_CATEGORIES）が配る。
// 画面が持つのは分類ごとのアイコンだけ。
type WeatherCodeCategory = (typeof vocabulary.weatherCategories)[number]["key"];

const CATEGORY_BY_CODE: ReadonlyMap<number, WeatherCodeCategory> = new Map(
  vocabulary.weatherCategories.flatMap((category) => category.codes.map((code) => [code, category.key] as const)),
);

export const WEATHER_CATEGORY_LABEL = Object.fromEntries(
  vocabulary.weatherCategories.map((category) => [category.key, category.label]),
) as Record<WeatherCodeCategory, string>;

// 「晴れ」以外は昼夜で見た目を変えない（昼夜どちらでも同じアイコンで伝わる）。
export const WEATHER_CATEGORY_ICON: Record<WeatherCodeCategory, (props: { size?: number }) => ReactElement> = {
  clear: SunIcon,
  cloudy: CloudIcon,
  fog: FogIcon,
  rain: RaindropIcon,
  snow: SnowflakeIcon,
  thunderstorm: ThunderIcon,
};

interface WeatherCodeDisplay {
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
  const category = weatherCategoryOf(weatherCode);
  return { Icon: WEATHER_CATEGORY_ICON[category], label: WEATHER_CATEGORY_LABEL[category] };
}

export function weatherCategoryOf(weatherCode: number): WeatherCodeCategory {
  return CATEGORY_BY_CODE.get(weatherCode) ?? vocabulary.weatherCategoryFallback;
}
