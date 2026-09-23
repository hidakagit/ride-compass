import type { ReactElement } from "react";
import { vocabulary } from "@/types/generated/vocabulary";
import { CloudIcon, FogIcon, RaindropIcon, SnowflakeIcon, SunIcon, ThunderIcon } from "@/components/ui/icons/icons";

// WMO天気コード（weather_code、backendが降水量・雲量・気温から導出）+ is_dayから、
// 「今日の見通し」（TodayOutlook）の天気アイコン1個を決める。実測値ベースの常設ヘッダーは
// 別の簡易分類を使う（amedasWeatherIcon.ts）。
//
// WMOコードの全パターンを個別に描き分けるのではなく、天候ヘッダーの小さい1アイコンに
// 収まる粒度（6カテゴリ）へ意図的に粗く丸める（「晴れ時々くもり」等の細かい中間状態は
// アイコンでは判別困難で、かえって視認性を落とすため）。
// 天気コードの分類と名前はbackendの宣言（domain/weather_display.py: WEATHER_CATEGORIES）が配る。
// 画面が持つのは分類ごとのアイコンだけ。
type WeatherCodeCategory = (typeof vocabulary.weatherCategories)[number]["key"];

const CATEGORY_BY_CODE: ReadonlyMap<number, WeatherCodeCategory> = new Map(
  vocabulary.weatherCategories.flatMap((category) => category.codes.map((code) => [code, category.key] as const)),
);

export const WEATHER_CATEGORY_LABEL = Object.fromEntries(
  vocabulary.weatherCategories.map((category) => [category.key, category.label]),
) as Record<WeatherCodeCategory, string>;

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
  const category = CATEGORY_BY_CODE.get(weatherCode) ?? vocabulary.weatherCategoryFallback;
  return { Icon: WEATHER_CATEGORY_ICON[category], label: WEATHER_CATEGORY_LABEL[category] };
}
