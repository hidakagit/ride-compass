import { RaindropIcon, ThermometerIcon, WindDirectionArrowIcon } from "@/components/Map/icons";
import type { AmedasObservation } from "@/types/weather";
import { classifyAmedasWeather, getAmedasWeatherDisplay } from "./amedasWeatherIcon";
import styles from "./WeatherPanel.module.css";

interface WeatherPanelProps {
  amedas: AmedasObservation | null;
  loading: boolean;
  error: string | null;
}

// 常設ヘッダーは予報ではなく最寄りアメダス観測所の実測値のみで構成する。
// TodayOutlook（今日の見通し、MSM予報）とは独立にフェッチするため、予報側の
// 障害・遅延から表示が影響を受けない。
//
// アメダスは観測専用APIのため、降水確率・weather_code（予報由来）はそのままでは
// 表示できない。代わりに:
// - 降水確率 → 実測の10分間降水量（precipitation_10min_mm）
// - 天気アイコン → 10分間日照時間・降水量・気温から簡易分類（amedasWeatherIcon.ts）
// - 突風 → アメダスの速報値レスポンスに突風フィールドが存在しないため非表示
//
// 日の出/日没は1日1個の値のため、このバーではなく「今日」パネル（TodayOutlook）が持つ
// ——バーは走行中に何度も見る瞬間値だけに絞る。
function isCurrentlyDay(sunrise: string | null, sunset: string | null): boolean {
  if (sunrise == null || sunset == null) return true;
  const now = Date.now();
  return now >= new Date(sunrise).getTime() && now < new Date(sunset).getTime();
}

export default function WeatherPanel({ amedas, loading, error }: WeatherPanelProps) {
  // 手元に観測値があるなら、直近の取り直しが失敗していてもそちらを出す（失敗の文言で
  // 値を置き換えない）。取得は一定間隔で続くため、回復すれば表示も戻る。
  if (!amedas) {
    if (loading) return <p className={styles.loading}>天候取得中...</p>;
    // 一般画面には短い文言だけを出し、原因の詳細（HTTPステータス等）はtitleへ回す。
    if (error) return <p className={styles.error} title={error}>観測値なし</p>;
    return null;
  }

  const temperatureTitle =
    amedas.apparent_temperature_c != null ? `体感 ${amedas.apparent_temperature_c.toFixed(1)}℃` : undefined;
  const windTitle = amedas.wind_direction_label != null ? `${amedas.wind_direction_label}の風` : undefined;

  const weatherCategory = classifyAmedasWeather(
    amedas.precipitation_10min_mm,
    amedas.sunshine_10min_minutes,
    amedas.temperature_c,
  );
  const weatherDisplay = getAmedasWeatherDisplay(weatherCategory, isCurrentlyDay(amedas.sunrise, amedas.sunset));

  return (
    // 気温・風向風速・降水量・天気アイコンをアイコン+数値だけの統計チップとして1行に並べる
    // （スマホ最適化方針、WeatherPanel.module.css参照）。
    <div className={styles.row}>
      <span className={styles.stat} title={temperatureTitle}>
        <ThermometerIcon size={16} />
        <span className={styles.srOnly}>気温: </span>
        {/* 数値と単位は1つのspanにまとめて.statのgapが間に入らないようにする
            （flexboxのgapは直接の子要素すべての間に均等に効くため、数値と単位を別々の
            子要素のままにすると、アイコン↔数値と同じ間隔が数値↔単位にも入ってしまい
            意図しない余白になる）。 */}
        <span>
          {amedas.temperature_c != null ? amedas.temperature_c.toFixed(1) : "-"}
          <span className={styles.unit}>℃</span>
        </span>
      </span>

      <span className={styles.divider} aria-hidden="true" />

      {amedas.wind_speed_ms != null && amedas.wind_direction_deg != null && (
        <span className={styles.stat} title={windTitle}>
          <span className={styles.windArrow} style={{ transform: `rotate(${amedas.wind_direction_deg + 180}deg)` }}>
            <WindDirectionArrowIcon size={16} />
          </span>
          <span className={styles.srOnly}>{amedas.wind_direction_label}の風: </span>
          <span>
            {amedas.wind_speed_ms.toFixed(1)}
            <span className={styles.unit}>m/s</span>
          </span>
        </span>
      )}

      {amedas.precipitation_10min_mm != null && (
        <>
          <span className={styles.divider} aria-hidden="true" />
          <span className={styles.stat} title="直近10分間の降水量">
            <RaindropIcon size={16} />
            <span className={styles.srOnly}>降水量: </span>
            <span>
              {amedas.precipitation_10min_mm.toFixed(1)}
              <span className={styles.unit}>mm</span>
            </span>
          </span>
        </>
      )}

      {weatherDisplay != null && (
        <>
          <span className={styles.divider} aria-hidden="true" />
          <span className={styles.stat} title={weatherDisplay.label}>
            <weatherDisplay.Icon size={16} />
            <span className={styles.srOnly}>天気: {weatherDisplay.label}</span>
          </span>
        </>
      )}
    </div>
  );
}
