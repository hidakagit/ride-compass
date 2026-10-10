import { vocabulary } from "@/types/generated/vocabulary";
import {
  CloudIcon,
  MoonIcon,
  RaindropIcon,
  SnowflakeIcon,
  SunIcon,
  type MapIconComponent,
} from "@/components/ui/icons/icons";

// WMO天気コード（weather_code。backendがアメダスと推計気象分布の観測から導く）の分類と名前は、backendの宣言
// （domain/weather_display.py: WEATHER_CATEGORIES）が配る。画面が持つのは分類ごとのアイコンだけ。
type WeatherCategory = (typeof vocabulary.weatherCategories)[number];
type WeatherCodeCategory = WeatherCategory["key"];

const CATEGORY_BY_CODE: ReadonlyMap<number, WeatherCategory> = new Map(
  vocabulary.weatherCategories.flatMap((category) => category.codes.map((code) => [code, category] as const)),
);

const WEATHER_CATEGORY_ICON: Record<WeatherCodeCategory, MapIconComponent> = {
  clear: SunIcon,
  cloudy: CloudIcon,
  rain: RaindropIcon,
  snow: SnowflakeIcon,
};

// 夜に絵を変える分類だけを持つ（ほかは昼夜どちらでも同じアイコンで伝わる）。
const NIGHT_ICON: Partial<Record<WeatherCodeCategory, MapIconComponent>> = { clear: MoonIcon };

interface AmedasWeatherDisplay {
  Icon: MapIconComponent;
  label: string;
}

/** backendが観測から導いた天気コード+昼夜フラグ（呼ぶ側が観測地点の日の出・日没から決める）から天気アイコン+ラベルを
 * 決める。コードが無い・分類に無ければnull（天気の分からないコードで、別の天気に見せない）。 */
export function getAmedasWeatherDisplay(weatherCode: number | null, isDay: boolean): AmedasWeatherDisplay | null {
  const category = weatherCode == null ? undefined : CATEGORY_BY_CODE.get(weatherCode);
  if (category === undefined) return null;
  const Icon = (!isDay && NIGHT_ICON[category.key]) || WEATHER_CATEGORY_ICON[category.key];
  return { Icon, label: category.label };
}
