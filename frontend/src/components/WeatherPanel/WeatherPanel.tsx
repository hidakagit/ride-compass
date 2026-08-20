import { RaindropIcon, SunIcon, ThermometerIcon, WindDirectionArrowIcon } from "@/components/Map/icons";
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

  // 体感温度・突風・降水量mm/hは元は括弧書きの文字列で常時併記していたが、狭いモバイル幅
  // （360px前後）だと折り返しが1文字ずつ縦積みになってしまう実機フィードバックを受け、
  // 常時表示はやめてtitle属性（長押し/ホバー）でのみ見せる補足に格下げした（アイコン+数値の
  // 1行化を優先する。スクリーンリーダー向けの内容はsrOnlyへ残す）。
  const temperatureTitle =
    weather.apparent_temperature_c != null ? `体感 ${weather.apparent_temperature_c.toFixed(1)}℃` : undefined;
  const windTitle = [
    `${weather.wind_direction_label}の風`,
    weather.wind_gusts_ms != null ? `突風 ${weather.wind_gusts_ms.toFixed(1)}m/s` : null,
  ]
    .filter(Boolean)
    .join(" / ");
  const precipitationTitle =
    weather.precipitation_mm != null ? `降水量 ${weather.precipitation_mm.toFixed(1)}mm/h` : undefined;

  return (
    // 気温・風向風速・降水確率・UV指数をアイコン+数値だけの統計チップとして1行に並べる
    // （スマホ実機フィードバック: 文字が多いと狭い幅で折り返し縦積みになる、上部バー最適化）。
    // 単位（℃/m/s/%）は数値より一段淡く小さくして、値と単位が視覚的に混ざらないようにしている。
    <div className={styles.row}>
      <span className={styles.stat} title={temperatureTitle}>
        <ThermometerIcon size={16} />
        <span className={styles.srOnly}>気温: </span>
        {weather.temperature_c.toFixed(1)}
        <span className={styles.unit}>℃</span>
      </span>

      <span className={styles.divider} aria-hidden="true" />

      {/* 向かい風・追い風がルート選定の判断材料になっている（route_preference.yamlの風関連重み）。
          矢印は風が吹いていく方向（wind_direction_degは気象学の慣習で「吹いてくる方向」
          のため+180度）へ向ける。文字ラベルは無くし、方向はアイコンの向きだけで示す。 */}
      <span className={styles.stat} title={windTitle}>
        <span
          className={styles.windArrow}
          style={{ transform: `rotate(${weather.wind_direction_deg + 180}deg)` }}
        >
          <WindDirectionArrowIcon size={16} />
        </span>
        <span className={styles.srOnly}>{weather.wind_direction_label}の風: </span>
        {weather.wind_speed_ms.toFixed(1)}
        <span className={styles.unit}>m/s</span>
      </span>

      {(weather.precipitation_probability_percent != null || weather.precipitation_mm != null) && (
        <>
          <span className={styles.divider} aria-hidden="true" />
          <span className={styles.stat} title={precipitationTitle}>
            <RaindropIcon size={16} />
            <span className={styles.srOnly}>降水確率: </span>
            {weather.precipitation_probability_percent != null && (
              <>
                {Math.round(weather.precipitation_probability_percent)}
                <span className={styles.unit}>%</span>
              </>
            )}
          </span>
        </>
      )}

      {weather.uv_index != null && (
        <>
          <span className={styles.divider} aria-hidden="true" />
          <span className={styles.stat} title="UV指数">
            <SunIcon size={16} />
            <span className={styles.srOnly}>UV指数: </span>
            {weather.uv_index.toFixed(1)}
          </span>
        </>
      )}
    </div>
  );
}
