import type { ReactElement } from "react";
import {
  CloudIcon,
  FogIcon,
  MoonIcon,
  RaindropIcon,
  SnowflakeIcon,
  SunIcon,
  ThunderIcon,
} from "@/components/Map/icons";

// Open-MeteoのWMO天気コード（weather_code）+ is_dayから、天候ヘッダーの天気アイコン1個を
// 決める。weather_codeなら昼夜を問わず常に意味のある値（快晴/くもり/雨等）が取れる
// （UV指数は夜間常に0.0になり情報価値が無い）。UV指数自体は数値としての価値が残るため
// チップのtitle属性へ格下げする（WeatherPanel.tsx参照）。
//
// WMOコードの全パターンを個別に描き分けるのではなく、天候ヘッダーの小さい1アイコンに
// 収まる粒度（6カテゴリ）へ意図的に粗く丸める（「晴れ時々くもり」等の細かい中間状態は
// アイコンでは判別困難で、かえって視認性を落とすため）。
export type WeatherCodeCategory = "clear" | "cloudy" | "fog" | "rain" | "snow" | "thunderstorm";

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

const CATEGORY_LABEL: Record<WeatherCodeCategory, string> = {
  clear: "快晴",
  cloudy: "くもり",
  fog: "霧",
  rain: "雨",
  snow: "雪",
  thunderstorm: "雷雨",
};

// 「快晴」以外は昼夜で見た目を変えない（くもり・雨・雪・霧・雷雨は昼夜どちらでも同じ
// アイコンで十分伝わり、6カテゴリ×2でアイコン数を倍にするほどの価値が無いため）。
const ICON_BY_CATEGORY: Record<Exclude<WeatherCodeCategory, "clear">, (props: { size?: number }) => ReactElement> = {
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

/** weather_code・is_dayから天気アイコン+ラベルを決める。weather_codeが無い（null）場合は
 * 何も表示すべきでないためnullを返す（呼び出し元はチップ自体を出さない）。 */
export function getWeatherCodeDisplay(weatherCode: number | null, isDay: number | null): WeatherCodeDisplay | null {
  if (weatherCode == null) return null;
  const category = CATEGORY_BY_CODE[weatherCode] ?? "cloudy";
  const label = CATEGORY_LABEL[category];
  if (category === "clear") {
    return { Icon: isDay === 0 ? MoonIcon : SunIcon, label };
  }
  return { Icon: ICON_BY_CATEGORY[category], label };
}
