import type { ReactElement } from "react";
import { vocabulary } from "@/types/generated/vocabulary";
import { CloudIcon, RaindropIcon, SnowflakeIcon, SunIcon } from "@/components/ui/icons/icons";

// WMO天気コード（weather_code。backendがアメダスの観測から導く）の分類ごとの天気アイコン。
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
  rain: RaindropIcon,
  snow: SnowflakeIcon,
};

/** 分類に無いコードはnull（天気の分からないコードで、別の天気に見せない）。 */
export function weatherCategoryOf(weatherCode: number): WeatherCodeCategory | null {
  return CATEGORY_BY_CODE.get(weatherCode) ?? null;
}
