import { WindIcon } from "@/components/Map/icons";
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
    <div className={styles.row}>
      {/* 向かい風・追い風がルート選定の判断材料になっている（route_preference.yamlの風関連重み）
          ことを踏まえ、風がこのヘッダの主眼だと一目で伝わるようアイコンを添える（T57） */}
      <WindIcon size={18} />
      <p className={styles.text}>
        {/* 「現在の天候:」の接頭辞は、狭いスマホ幅（360px等）で1行に収まらず折り返して
            ヘッダが縦に伸びる原因になっていたため廃止した。左のアイコンとheaderのtitle属性
            （長押し/ホバーで「風向・風速はルート候補の評価に使われます」）で文脈は伝わる。 */}
        {weather.temperature_c.toFixed(1)}℃ / {weather.wind_direction_label}の風{" "}
        {weather.wind_speed_ms.toFixed(1)} m/s
        {weather.precipitation_probability_percent != null &&
          ` / 降水確率 ${Math.round(weather.precipitation_probability_percent)}%`}
      </p>
    </div>
  );
}
