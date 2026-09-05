import { ClockIcon, RaindropIcon, ThermometerIcon, WindDirectionArrowIcon } from "@/components/Map/icons";
import type { AmedasObservation } from "@/types/weather";
import { classifyAmedasWeather, getAmedasWeatherDisplay } from "./amedasWeatherIcon";
import styles from "./WeatherPanel.module.css";

interface WeatherPanelProps {
  amedas: AmedasObservation | null;
  loading: boolean;
  error: string | null;
}

// 常設ヘッダーはOpen-Meteo（予報）ではなく最寄りアメダス観測所の実測値のみで構成する。
// TodayOutlook（今日の見通し、Open-Meteo）とは独立にフェッチするため、Open-Meteoの
// 障害・遅延から表示が影響を受けない。
//
// アメダスは観測専用APIのため、降水確率・weather_code（予報由来）はそのままでは
// 表示できない。代わりに:
// - 降水確率 → 実測の10分間降水量（precipitation_10min_mm）
// - 天気アイコン → 10分間日照時間・降水量・気温から簡易分類（amedasWeatherIcon.ts）
// - 突風 → アメダスの速報値レスポンスに突風フィールドが存在しないため非表示
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

// 実行環境のローカルタイムゾーンに左右されないよう常にJSTで整形する（dynamicWeather.ts:
// formatDynamicFrameHourMinuteと同じ理由。getHours()/getMinutes()はホストマシンの
// ローカルタイムゾーンに依存するため、UTC環境（CI等）で実行すると日没時刻が9時間ずれる
// バグがあった）。
function formatClockTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "--:--";
  return date.toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Tokyo" });
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

      {/* 天気アイコン＋日の出/日没を1チップへ統合してある。.weatherStatsは
          flex-shrink: 0で常に自然幅を保つ設計（page.module.css参照）のため、チップを
          1個増やすと右側の.headerActions（警報バッジ・デバッグアイコン）を押し出して
          隠してしまう。日の出/日没チップを新設で独立させず、既に昼夜判定のため
          sunrise/sunsetを参照している天気アイコンチップへ統合し、正味のチップ数を
          増やさないようにした（情報量は維持——アイコン＋時刻の両方を引き続き表示する）。 */}
      {(weatherDisplay != null || twilightIso != null) && (
        <>
          <span className={styles.divider} aria-hidden="true" />
          <span
            className={styles.stat}
            title={[weatherDisplay?.label, twilightIso != null ? `${twilightTitle} ${formatClockTime(twilightIso)}` : null]
              .filter(Boolean)
              .join(" / ")}
          >
            {weatherDisplay ? <weatherDisplay.Icon size={16} /> : <ClockIcon size={15} />}
            <span className={styles.srOnly}>
              {weatherDisplay ? `天気: ${weatherDisplay.label}` : ""}
              {twilightIso != null ? `${twilightTitle}: ` : ""}
            </span>
            {twilightIso != null && (
              // 「天気アイコン＋時刻」だけでは何の時刻か伝わらないため、昇る/沈むを
              // 直感的に示す矢印を時刻の直前に添える（多くの天気アプリで使われる日の出↑/
              // 日没↓の慣習的表現。時計アイコンより幅を取らず、天気アイコンと組み合わせても
              // 意味の混同が起きない）。矢印と時刻は1つのspanにまとめ、.statのgapが間に
              // 入って離れて見えないようにする（数値・単位と同じ理由）。
              <span>
                <span className={styles.twilightArrow} aria-hidden="true">
                  {beforeSunrise ? "↑" : "↓"}
                </span>
                {formatClockTime(twilightIso)}
              </span>
            )}
          </span>
        </>
      )}
    </div>
  );
}
