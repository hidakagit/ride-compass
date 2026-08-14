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
    <p className={styles.text}>
      現在の天候: {weather.temperature_c.toFixed(1)}℃ / {weather.wind_direction_label}の風{" "}
      {weather.wind_speed_ms.toFixed(1)} m/s
      {weather.precipitation_probability_percent != null &&
        ` / 降水確率 ${Math.round(weather.precipitation_probability_percent)}%`}
    </p>
  );
}
