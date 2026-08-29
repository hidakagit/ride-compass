import { ClockIcon, RaindropIcon, ThermometerIcon, WindDirectionArrowIcon } from "@/components/Map/icons";
import type { AmedasObservation } from "@/types/weather";
import { classifyAmedasWeather, getAmedasWeatherDisplay } from "./amedasWeatherIcon";
import styles from "./WeatherPanel.module.css";

interface WeatherPanelProps {
  amedas: AmedasObservation | null;
  loading: boolean;
  error: string | null;
}

// 改善計画T387フォローアップ（ユーザー指示2026-08-29「常設エリアは実測値、今日の見通しは
// 予測値」）: 常設ヘッダーはOpen-Meteo（予報）ではなく最寄りアメダス観測所の実測値のみで
// 構成する。TodayOutlook（今日の見通し、Open-Meteo）とは独立にフェッチするため、
// Open-Meteoの障害・遅延から表示が影響を受けない。
//
// アメダスは観測専用APIのため、Open-Meteo版（旧WeatherConditions props）で表示していた
// 降水確率・weather_code（予報由来）はそのままでは表示できない。代わりに:
// - 降水確率 → 実測の10分間降水量（precipitation_10min_mm）
// - 天気アイコン → 10分間日照時間・降水量・気温から簡易分類（amedasWeatherIcon.ts）
// - 突風 → アメダスの速報値レスポンスに突風フィールドが存在しないため非表示（実データ確認済み）
// - 日の出/日没 → 新規チップとして追加（予報不要のためアメダスのレスポンスにastralの
//   ローカル計算結果が乗っている、backend側で計算済み）
function isCurrentlyDay(sunrise: string | null, sunset: string | null): boolean {
  if (sunrise == null || sunset == null) return true;
  const now = Date.now();
  return now >= new Date(sunrise).getTime() && now < new Date(sunset).getTime();
}

function isBeforeSunrise(sunrise: string | null): boolean {
  return sunrise != null && Date.now() < new Date(sunrise).getTime();
}

function formatClockTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "--:--";
  return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

export default function WeatherPanel({ amedas, loading, error }: WeatherPanelProps) {
  if (loading) return <p className={styles.loading}>天候取得中...</p>;
  if (error) return <p className={styles.error}>{error}</p>;
  if (!amedas) return null;

  const temperatureTitle =
    amedas.apparent_temperature_c != null ? `体感 ${amedas.apparent_temperature_c.toFixed(1)}℃` : undefined;
  const windTitle = amedas.wind_direction_label != null ? `${amedas.wind_direction_label}の風` : undefined;

  const weatherCategory = classifyAmedasWeather(
    amedas.precipitation_10min_mm,
    amedas.sunshine_10min_minutes,
    amedas.temperature_c,
  );
  const weatherDisplay = getAmedasWeatherDisplay(weatherCategory, isCurrentlyDay(amedas.sunrise, amedas.sunset));

  const beforeSunrise = isBeforeSunrise(amedas.sunrise);
  const twilightIso = beforeSunrise ? amedas.sunrise : amedas.sunset;
  const twilightTitle = twilightIso != null ? (beforeSunrise ? "日の出" : "日没") : undefined;

  return (
    // 気温・風向風速・降水量・天気アイコン・日の出日没をアイコン+数値だけの統計チップとして
    // 1行に並べる（既存のOpen-Meteo版と同じスマホ最適化方針、WeatherPanel.module.css参照）。
    <div className={styles.row}>
      <span className={styles.stat} title={temperatureTitle}>
        <ThermometerIcon size={16} />
        <span className={styles.srOnly}>気温: </span>
        {amedas.temperature_c != null ? amedas.temperature_c.toFixed(1) : "-"}
        <span className={styles.unit}>℃</span>
      </span>

      <span className={styles.divider} aria-hidden="true" />

      {amedas.wind_speed_ms != null && amedas.wind_direction_deg != null && (
        <span className={styles.stat} title={windTitle}>
          <span className={styles.windArrow} style={{ transform: `rotate(${amedas.wind_direction_deg + 180}deg)` }}>
            <WindDirectionArrowIcon size={16} />
          </span>
          <span className={styles.srOnly}>{amedas.wind_direction_label}の風: </span>
          {amedas.wind_speed_ms.toFixed(1)}
          <span className={styles.unit}>m/s</span>
        </span>
      )}

      {amedas.precipitation_10min_mm != null && (
        <>
          <span className={styles.divider} aria-hidden="true" />
          <span className={styles.stat} title="直近10分間の降水量">
            <RaindropIcon size={16} />
            <span className={styles.srOnly}>降水量: </span>
            {amedas.precipitation_10min_mm.toFixed(1)}
            <span className={styles.unit}>mm</span>
          </span>
        </>
      )}

      {weatherDisplay && (
        <>
          <span className={styles.divider} aria-hidden="true" />
          <span className={styles.stat} title={weatherDisplay.label}>
            <weatherDisplay.Icon size={16} />
            <span className={styles.srOnly}>天気: {weatherDisplay.label}</span>
          </span>
        </>
      )}

      {twilightIso != null && (
        <>
          <span className={styles.divider} aria-hidden="true" />
          <span className={styles.stat} title={twilightTitle}>
            <ClockIcon size={15} />
            <span className={styles.srOnly}>{twilightTitle}: </span>
            {formatClockTime(twilightIso)}
          </span>
        </>
      )}
    </div>
  );
}
