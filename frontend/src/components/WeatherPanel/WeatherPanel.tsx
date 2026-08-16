import { RaindropIcon, ThermometerIcon, WindIcon } from "@/components/Map/icons";
import type { WeatherConditions } from "@/types/weather";
import styles from "./WeatherPanel.module.css";

interface WeatherPanelProps {
  weather: WeatherConditions | null;
  loading: boolean;
  error: string | null;
}

export default function WeatherPanel({ weather, loading, error }: WeatherPanelProps) {
  if (loading) return <p className={styles.loading}>天候取得中...</p>;
  if (error) return <p className={styles.error}>{error}</p>;
  if (!weather) return null;

  return (
    // 以前は気温・風向風速・降水確率を"/"区切りの1文で並べていたが、区切りの"/"と
    // 風速の単位"m/s"の"/"が混ざって見え読みにくいという実機フィードバック（T61）を受け、
    // 項目ごとにアイコン+区切り線を置く「統計チップ」の並びへ変更した。単位（℃/m/s/%）は
    // 数値より一段淡く小さくして、値と単位が視覚的に混ざらないようにしている。
    <div className={styles.row}>
      <span className={styles.stat}>
        <ThermometerIcon size={16} />
        <span className={styles.srOnly}>気温: </span>
        {weather.temperature_c.toFixed(1)}
        <span className={styles.unit}>℃</span>
      </span>

      <span className={styles.divider} aria-hidden="true" />

      {/* 向かい風・追い風がルート選定の判断材料になっている（route_preference.yamlの風関連重み） */}
      <span className={styles.stat}>
        <WindIcon size={16} />
        <span className={styles.srOnly}>風: </span>
        {weather.wind_direction_label}の風 {weather.wind_speed_ms.toFixed(1)}{" "}
        <span className={styles.unit}>m/s</span>
      </span>

      {weather.precipitation_probability_percent != null && (
        <>
          <span className={styles.divider} aria-hidden="true" />
          <span className={styles.stat}>
            <RaindropIcon size={16} />
            <span className={styles.srOnly}>降水確率: </span>
            {Math.round(weather.precipitation_probability_percent)}
            <span className={styles.unit}>%</span>
          </span>
        </>
      )}
    </div>
  );
}
