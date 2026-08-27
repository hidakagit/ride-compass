"use client";

import * as Popover from "@radix-ui/react-popover";
import { ClockIcon, RaindropIcon, SunIcon, ThermometerIcon, WindIcon } from "@/components/Map/icons";
import { getWeatherCodeDisplay } from "@/components/WeatherPanel/weatherCode";
import type { WeatherConditions, WeatherPeriodOutlook } from "@/types/weather";
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

// today_periodsの各コマ（06:00〜20:00の代表時刻文字列"HH:MM"）の頭2桁を「6時」のような
// 短い表示ラベルへ整形する（フロントの担当、weather.pyのdocstring参照）。
function formatPeriodLabel(period: string): string {
  const hour = Number.parseInt(period.slice(0, 2), 10);
  return Number.isNaN(hour) ? period : `${hour}時`;
}

function PeriodSlot({ period }: { period: WeatherPeriodOutlook }) {
  // 天気の流れは06:00〜20:00（常に日中）のコマのみのため、isDayは常に1固定でよい
  // （weather_code自体はcurrentと同じ判定ロジック、weatherCode.ts参照）。
  const display = getWeatherCodeDisplay(period.weather_code, 1);
  return (
    <div className={styles.periodSlot}>
      <span className={styles.periodTime}>{formatPeriodLabel(period.period)}</span>
      {display ? <display.Icon size={17} /> : <span className={styles.periodIconFallback}>-</span>}
      <span className={styles.periodTemp}>
        {period.temperature_c != null ? `${Math.round(period.temperature_c)}℃` : "-"}
      </span>
      <span className={styles.periodPrecip}>
        {period.precipitation_probability_percent != null
          ? `${Math.round(period.precipitation_probability_percent)}%`
          : "-"}
      </span>
    </div>
  );
}

export default function TodayOutlook({ weather }: TodayOutlookProps) {
  if (!weather) return null;

  const hasFlow = weather.today_periods.length > 0;
  const hasAnyOutlookStat =
    weather.sunset != null ||
    weather.precipitation_probability_max_percent != null ||
    weather.wind_speed_max_ms != null ||
    weather.temperature_max_c != null ||
    weather.temperature_min_c != null ||
    weather.uv_index_max != null ||
    hasFlow;
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
            {weather.uv_index_max != null && (
              <div className={styles.item}>
                <SunIcon size={15} />
                <span>
                  <span className={styles.label}>UV指数（最大）</span>
                  <span className={styles.value}>{weather.uv_index_max.toFixed(1)}</span>
                </span>
              </div>
            )}
          </div>
          {hasFlow && (
            <div className={styles.flow}>
              <p className={styles.flowTitle}>天気の流れ</p>
              {/* 8コマがスマホ横幅に収まりきらない場合はパネル内だけで横スクロールさせる
                  （ユーザーからの明示許可: 「収まらない場合、天気の流れのところは
                  横スクロールがパネル内で発生してもいい」）。 */}
              <div className={styles.flowScroll}>
                {weather.today_periods.map((period) => (
                  <PeriodSlot key={period.period} period={period} />
                ))}
              </div>
            </div>
          )}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
