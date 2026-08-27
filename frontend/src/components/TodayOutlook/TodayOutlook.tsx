"use client";

import * as Popover from "@radix-ui/react-popover";
import { ClockIcon, RaindropIcon, ThermometerIcon, WindIcon } from "@/components/Map/icons";
import type { WeatherConditions } from "@/types/weather";
import styles from "./TodayOutlook.module.css";

interface TodayOutlookProps {
  weather: WeatherConditions | null;
}

// 改善計画T385: 「今日の見通し」二次パネル。常設ヘッダー（.weatherStats）はどの季節・
// 地域でも常に意味を持つ瞬間値（気温・風・降水確率・天気アイコン）だけに絞り、
// 「日没時刻・今日の降水確率最大・今日の最大風速・今日の気温レンジ」という1日1個の値は
// タップで開く本パネルへ集約する（T384調査の結論: 常設ヘッダーへ項目を足さず、
// 個別ON/OFF設定も新設せず、既存のWarningBadgeListと同じPopoverパターンで済ませる）。

function formatClockTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "--:--";
  return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

// 日没までの残り時間を「あと3時間12分」の形にする。日本は夏時間が無くタイムゾーンの
// 揺れが無いため、単純な差分計算で十分（sunsetはOpen-Meteoからtimezone=Asia/Tokyo指定で
// 取得した現地時刻の文字列、ブラウザのローカル時刻もJST想定で比較する）。
function formatRemainingUntil(iso: string): string | null {
  const target = new Date(iso).getTime();
  if (Number.isNaN(target)) return null;
  const diffMs = target - Date.now();
  if (diffMs <= 0) return "日没済み";
  const totalMinutes = Math.round(diffMs / 60000);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return hours > 0 ? `あと${hours}時間${minutes}分` : `あと${minutes}分`;
}

export default function TodayOutlook({ weather }: TodayOutlookProps) {
  if (!weather) return null;

  const hasAnyOutlookStat =
    weather.sunset != null ||
    weather.precipitation_probability_max_percent != null ||
    weather.wind_speed_max_ms != null ||
    weather.temperature_max_c != null ||
    weather.temperature_min_c != null;
  // 取得失敗・キャッシュ欠落等でdaily側が丸ごと無い場合は、トグル自体を出さない
  // （空のパネルを開けるだけの無意味なボタンを残さない）。
  if (!hasAnyOutlookStat) return null;

  return (
    <Popover.Root>
      <Popover.Trigger asChild>
        <button type="button" className={styles.trigger} aria-label="今日の見通しを表示">
          今日
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content className={styles.panel} side="bottom" align="start" sideOffset={6}>
          <p className={styles.title}>今日の見通し</p>
          <div className={styles.grid}>
            {weather.sunset != null && (
              <div className={styles.item}>
                <ClockIcon size={15} />
                <span>
                  <span className={styles.label}>日没</span>
                  <span className={styles.value}>
                    {formatClockTime(weather.sunset)}
                    <span className={styles.sub}>{formatRemainingUntil(weather.sunset)}</span>
                  </span>
                </span>
              </div>
            )}
            {weather.precipitation_probability_max_percent != null && (
              <div className={styles.item}>
                <RaindropIcon size={15} />
                <span>
                  <span className={styles.label}>降水確率（最大）</span>
                  <span className={styles.value}>
                    {Math.round(weather.precipitation_probability_max_percent)}
                    <span className={styles.unit}>%</span>
                  </span>
                </span>
              </div>
            )}
            {weather.wind_speed_max_ms != null && (
              <div className={styles.item}>
                <WindIcon size={15} />
                <span>
                  <span className={styles.label}>風（最大）</span>
                  <span className={styles.value}>
                    {weather.wind_speed_max_ms.toFixed(1)}
                    <span className={styles.unit}>m/s</span>
                  </span>
                </span>
              </div>
            )}
            {(weather.temperature_max_c != null || weather.temperature_min_c != null) && (
              <div className={styles.item}>
                <ThermometerIcon size={15} />
                <span>
                  <span className={styles.label}>気温</span>
                  <span className={styles.value}>
                    {weather.temperature_min_c != null && `${Math.round(weather.temperature_min_c)}℃〜`}
                    {weather.temperature_max_c != null && `${Math.round(weather.temperature_max_c)}℃`}
                  </span>
                </span>
              </div>
            )}
          </div>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
