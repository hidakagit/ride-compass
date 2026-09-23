"use client";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/Popover/Popover";
import { ClockIcon, RaindropIcon, ThermometerIcon, WindIcon } from "@/components/ui/icons/icons";
import { formatDynamicFrameHourMinute } from "@/lib/frameTime";
import { getWeatherCodeDisplay } from "@/features/conditions/WeatherPanel/weatherCode";
import type { WeatherConditions, WeatherPeriodOutlook } from "@/types/weather";
import { Button } from "@/components/ui/Button/Button";
import { textVariants } from "@/components/ui/Text/Text";
import { cn } from "@/lib/cn";

interface TodayOutlookProps {
  weather: WeatherConditions | null;
  loading: boolean;
  error: string | null;
}

// 「今日の見通し」二次パネル。常設ヘッダー（.weatherStats）はどの季節・
// 地域でも常に意味を持つ瞬間値（気温・風・降水量・天気アイコン）だけに絞り、
// 「今日の最大降水量・今日の最大風速・今日の気温レンジ」という1日1個の値はタップで
// 開く本パネルへ集約する（常設ヘッダーへ項目を足さず、個別ON/OFF設定も新設せず、
// 既存のWarningBadgeListと同じPopoverパターンで済ませる）。
// 日の出/日没も1日1個の値のためここへ置く（常設ヘッダーは走行中に何度も見る瞬間値だけに
// 絞る）。値はMSM予報のレスポンスに乗っている（backend側でastralが計算する）。

/** 日の出・日没の時刻（JST）。壊れた値は「--:--」にして行ごと落とさない。 */
function formatClockTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "--:--";
  return formatDynamicFrameHourMinute(date);
}

// today_periodsの各コマ（2時間おきの代表時刻文字列"HH:MM"）の頭2桁を「6時」のような
// 短い表示ラベルへ整形する（フロントの担当、weather.pyのdocstring参照）。
function formatPeriodLabel(period: string): string {
  const hour = Number.parseInt(period.slice(0, 2), 10);
  return Number.isNaN(hour) ? period : `${hour}時`;
}

// 予想降水量。降らない見込み（0.1mm未満）は「-」。単位はコマ単体で意味が読み取れるよう
// 各コマへ付ける（横スクロールで見出しが画面外へ出るため）。
function formatPrecipitation(mm: number): string {
  return mm < 0.1 ? "-" : `${mm.toFixed(1)}mm`;
}

function PeriodSlot({ period }: { period: WeatherPeriodOutlook }) {
  // today_periodsは昼夜どちらのコマも含みうる（現在時刻を含む区間から2時間毎）が、
  // is_dayをコマ単位では取得していないため、
  const display = getWeatherCodeDisplay(period.weather_code);
  return (
    <div className="flex w-10 flex-shrink-0 flex-col items-center gap-1 text-[var(--color-accent)]">
      <span className={cn(textVariants({ variant: "note" }), "tabular-nums")}>{formatPeriodLabel(period.period)}</span>
      {display ? <display.Icon size={17} /> : <span className="text-[var(--color-muted)]">-</span>}
      <span className="text-[length:var(--font-size-sm)] font-semibold text-[var(--foreground)] tabular-nums">
        {period.temperature_c != null ? `${Math.round(period.temperature_c)}℃` : "-"}
      </span>
      <span className={cn(textVariants({ variant: "note" }), "tabular-nums")}>
        {period.precipitation_mm != null ? formatPrecipitation(period.precipitation_mm) : "-"}
      </span>
    </div>
  );
}

export default function TodayOutlook({ weather, loading, error }: TodayOutlookProps) {
  // weather===nullは「取得失敗」「まだ読み込み中」「意味のある値が無い」のいずれの
  // 可能性もあるため、取得が実際に失敗した場合は警戒色のトリガーで気づけるようにする
  // （開くとエラー内容を示す最小限のパネル）。手元に見通しがあるなら、直近の取り直しが
  // 失敗していてもそちらを優先する（WeatherPanelと同じ扱い）。
  if (error && !weather) {
    return (
      <Popover>
        <PopoverTrigger asChild>
          <Button
            variant="danger"
            size="xs"
            shape="pill"
            className="font-semibold"
            aria-label="今日の見通しの取得に失敗しました"
          >
            今日
          </Button>
        </PopoverTrigger>
        <PopoverContent
          layer="header"
          className="w-76 max-w-[calc(100vw-2*var(--space-3))]"
          side="bottom"
          align="start"
        >
          <p className={cn(textVariants({ variant: "note" }), "mb-2 font-bold tracking-wide uppercase")}>
            今日の見通し
          </p>
          <p>取得に失敗しました: {error}</p>
        </PopoverContent>
      </Popover>
    );
  }
  // ロード中はまだ何とも言えないため、直前の表示を保つよりチラつきを避けて何も出さない
  // （常設ヘッダーのWeatherPanelと違いこのパネルはトグル自体の有無が変わるため、
  // ロード中に一瞬でも「意味のある値が無い」扱いのnullへ倒れると点滅して見える）。
  if (loading || !weather) return null;

  const hasFlow = weather.today_periods.length > 0;
  const hasTwilight = weather.sunrise != null || weather.sunset != null;
  const hasAnyOutlookStat =
    weather.precipitation_max_mm != null ||
    weather.wind_speed_max_ms != null ||
    weather.temperature_max_c != null ||
    weather.temperature_min_c != null ||
    hasTwilight ||
    hasFlow;
  // キャッシュ欠落等でdaily側が丸ごと無い場合は、トグル自体を出さない
  // （空のパネルを開けるだけの無意味なボタンを残さない）。
  if (!hasAnyOutlookStat) return null;

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button size="xs" shape="pill" className="bg-transparent font-semibold" aria-label="今日の見通しを表示">
          今日
        </Button>
      </PopoverTrigger>
      <PopoverContent layer="header" className="w-76 max-w-[calc(100vw-2*var(--space-3))]" side="bottom" align="start">
        <p className={cn(textVariants({ variant: "note" }), "mb-2 font-bold tracking-wide uppercase")}>今日の見通し</p>
        <div className="grid grid-cols-2 gap-x-3 gap-y-2">
          {weather.precipitation_max_mm != null && (
            <div className="flex items-start gap-1.5 text-[var(--color-accent)] [&_svg]:mt-0.5 [&_svg]:shrink-0">
              <RaindropIcon size={15} />
              <span>
                <span className={cn(textVariants({ variant: "note" }), "block")}>降水量（最大）</span>
                <span className="block text-[length:var(--font-size-md)] leading-[1.3] font-semibold text-[var(--foreground)]">
                  {weather.precipitation_max_mm.toFixed(1)}
                  <span className="text-[0.75em] font-normal text-[var(--color-muted)]">mm/h</span>
                </span>
              </span>
            </div>
          )}
          {weather.wind_speed_max_ms != null && (
            <div className="flex items-start gap-1.5 text-[var(--color-accent)] [&_svg]:mt-0.5 [&_svg]:shrink-0">
              <WindIcon size={15} />
              <span>
                <span className={cn(textVariants({ variant: "note" }), "block")}>風（最大）</span>
                <span className="block text-[length:var(--font-size-md)] leading-[1.3] font-semibold text-[var(--foreground)]">
                  {weather.wind_speed_max_ms.toFixed(1)}
                  <span className="text-[0.75em] font-normal text-[var(--color-muted)]">m/s</span>
                </span>
              </span>
            </div>
          )}
          {(weather.temperature_max_c != null || weather.temperature_min_c != null) && (
            <div className="flex items-start gap-1.5 text-[var(--color-accent)] [&_svg]:mt-0.5 [&_svg]:shrink-0">
              <ThermometerIcon size={15} />
              <span>
                <span className={cn(textVariants({ variant: "note" }), "block")}>気温</span>
                <span className="block text-[length:var(--font-size-md)] leading-[1.3] font-semibold text-[var(--foreground)]">
                  {weather.temperature_min_c != null && `${Math.round(weather.temperature_min_c)}℃〜`}
                  {weather.temperature_max_c != null && `${Math.round(weather.temperature_max_c)}℃`}
                </span>
              </span>
            </div>
          )}
          {hasTwilight && (
            <div className="flex items-start gap-1.5 text-[var(--color-accent)] [&_svg]:mt-0.5 [&_svg]:shrink-0">
              <ClockIcon size={15} />
              <span>
                <span className={cn(textVariants({ variant: "note" }), "block")}>日の出・日没</span>
                <span className="block text-[length:var(--font-size-md)] leading-[1.3] font-semibold text-[var(--foreground)]">
                  {weather.sunrise != null ? formatClockTime(weather.sunrise) : "--:--"}
                  <span className="text-[0.75em] font-normal text-[var(--color-muted)]">〜</span>
                  {weather.sunset != null ? formatClockTime(weather.sunset) : "--:--"}
                </span>
              </span>
            </div>
          )}
        </div>
        {hasFlow && (
          <div className="mt-2 border-t border-[var(--color-border)] pt-2">
            <p className={cn(textVariants({ variant: "note" }), "mb-1")}>天気の流れ</p>
            {/* コマがスマホ横幅に収まりきらない場合は、パネル内だけで横スクロールさせる。 */}
            <div className="-mx-3 flex gap-2 overflow-x-auto px-3 pb-0.5">
              {weather.today_periods.map((period) => (
                <PeriodSlot key={period.period} period={period} />
              ))}
            </div>
          </div>
        )}
      </PopoverContent>
    </Popover>
  );
}
