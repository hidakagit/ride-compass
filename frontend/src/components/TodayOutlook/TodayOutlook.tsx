"use client";

import * as Popover from "@radix-ui/react-popover";
import { RaindropIcon, SunIcon, ThermometerIcon, WindIcon } from "@/components/Map/icons";
import { getWeatherCodeDisplay } from "@/components/WeatherPanel/weatherCode";
import type { WeatherConditions, WeatherPeriodOutlook } from "@/types/weather";
import styles from "./TodayOutlook.module.css";

interface TodayOutlookProps {
  weather: WeatherConditions | null;
  loading: boolean;
  error: string | null;
}

// 改善計画T385: 「今日の見通し」二次パネル。常設ヘッダー（.weatherStats）はどの季節・
// 地域でも常に意味を持つ瞬間値（気温・風・降水量・天気アイコン）だけに絞り、
// 「今日の降水確率最大・今日の最大風速・今日の気温レンジ・UV指数最大」という1日1個の
// 値はタップで開く本パネルへ集約する（T384調査の結論: 常設ヘッダーへ項目を足さず、
// 個別ON/OFF設定も新設せず、既存のWarningBadgeListと同じPopoverパターンで済ませる）。
// 日の出/日没は改善計画T387フォローアップ（ユーザー指示2026-08-29「日の出日没も予報が
// 不要なので上部常設バーに移動」）で常設ヘッダー（WeatherPanel）へ移設したため、
// ここには表示しない（予報専用パネルという位置づけがより明確になった）。

// today_periodsの各コマ（2時間おきの代表時刻文字列"HH:MM"）の頭2桁を「6時」のような
// 短い表示ラベルへ整形する（フロントの担当、weather.pyのdocstring参照）。
function formatPeriodLabel(period: string): string {
  const hour = Number.parseInt(period.slice(0, 2), 10);
  return Number.isNaN(hour) ? period : `${hour}時`;
}

function PeriodSlot({ period }: { period: WeatherPeriodOutlook }) {
  // today_periodsは昼夜どちらのコマも含みうる（現在時刻を含む区間から2時間毎、
  // 改善計画T385フォローアップ2）が、is_dayをコマ単位では取得していないため、
  // isDayは便宜的に常に1固定で渡す（「快晴」カテゴリの昼夜アイコン切替のみに影響し、
  // 実害は小さいと判断。weather_code自体の判定ロジックはweatherCode.ts参照）。
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

export default function TodayOutlook({ weather, loading, error }: TodayOutlookProps) {
  // 改善計画T387フォローアップ（ユーザー指示2026-08-29「取得失敗したことを何かパネルで
  // わかるようにして」）: 以前はweather===nullを「取得失敗」「まだ読み込み中」「意味のある
  // 値が無い」の区別なく同じ扱い（トグル自体を出さない）にしていた。取得が実際に失敗した
  // 場合は警戒色のトリガーで気づけるようにする（開くとエラー内容を示す最小限のパネル）。
  if (error) {
    return (
      <Popover.Root>
        <Popover.Trigger asChild>
          <button type="button" className={styles.triggerError} aria-label="今日の見通しの取得に失敗しました">
            今日
          </button>
        </Popover.Trigger>
        <Popover.Portal>
          <Popover.Content className={styles.panel} side="bottom" align="start" sideOffset={6}>
            <p className={styles.title}>今日の見通し</p>
            <p>取得に失敗しました: {error}</p>
          </Popover.Content>
        </Popover.Portal>
      </Popover.Root>
    );
  }
  // ロード中はまだ何とも言えないため、直前の表示を保つよりチラつきを避けて何も出さない
  // （常設ヘッダーのWeatherPanelと違いこのパネルはトグル自体の有無が変わるため、
  // ロード中に一瞬でも「意味のある値が無い」扱いのnullへ倒れると点滅して見える）。
  if (loading || !weather) return null;

  const hasFlow = weather.today_periods.length > 0;
  const hasAnyOutlookStat =
    weather.precipitation_probability_max_percent != null ||
    weather.wind_speed_max_ms != null ||
    weather.temperature_max_c != null ||
    weather.temperature_min_c != null ||
    weather.uv_index_max != null ||
    hasFlow;
  // キャッシュ欠落等でdaily側が丸ごと無い場合は、トグル自体を出さない
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
