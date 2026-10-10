"use client";

import type { ReactNode } from "react";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/Popover/Popover";
import { ClockIcon, RaindropIcon, ThermometerIcon, WindIcon } from "@/components/ui/icons/icons";
import { formatJstHourMinute } from "@/lib/time";
import type { WeatherConditions, WeatherPeriodOutlook } from "@/types/weather";
import weatherScales from "@/types/generated/weather-scales.json";
import { Button } from "@/components/ui/Button/Button";
import { textVariants } from "@/components/ui/Text/Text";
import { cn } from "@/lib/cn";

interface TodayOutlookProps {
  weather: WeatherConditions | null;
  loading: boolean;
  error: string | null;
}

// 「今日」の二次パネル。常設ヘッダーはどの季節・
// 地域でも常に意味を持つ瞬間値（気温・風・降水量・天気アイコン）だけに絞り、
// 「今日の最大降水量・今日の最大風速・今日の気温レンジ」という1日1個の値はタップで
// 開く本パネルへ集約する（常設ヘッダーへ項目を足さず、個別ON/OFF設定も新設せず、
// 既存のWarningBadgeListと同じPopoverパターンで済ませる）。
// 日の出/日没も1日1個の値のためここへ置く（常設ヘッダーは走行中に何度も見る瞬間値だけに
// 絞る）。日の出/日没は天文計算の値のため「モデルの計算値」の見出しの外（上）に置く。それ以外は
// 数値予報モデル（MSM）の計算値で、「予報」と呼ばず、天気（晴れ・雨等）も出さない——どちらも気象業務法の予報業務の許可の対象と気象庁の公式の説明が書いている
// （docs/architecture/data-sources.md「気象業務法の予報業務許可」節）。

/** 日の出・日没の時刻（JST）。壊れた値は「--:--」にして行ごと落とさない。 */
function formatClockTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "--:--";
  return formatJstHourMinute(date);
}

// today_periodsの各コマ（代表時刻文字列"HH:MM"）の頭2桁を「6時」のような
// 短い表示ラベルへ整形する（フロントの担当、weather.pyのdocstring参照）。
function formatPeriodLabel(period: string): string {
  const hour = Number.parseInt(period.slice(0, 2), 10);
  return Number.isNaN(hour) ? period : `${hour}時`;
}

// 降水量。backendの「降っていない」の境未満は「-」。単位はコマ単体で意味が読み取れるよう
// 各コマへ付ける（横スクロールで見出しが画面外へ出るため）。
function formatPrecipitation(mm: number): string {
  return mm < weatherScales.precipitation_none_below_mm ? "-" : `${mm.toFixed(1)}mm`;
}

function DailyStat({
  icon,
  term,
  className,
  children,
}: {
  icon: ReactNode;
  term: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div className={cn("flex items-start gap-1.5 text-[var(--color-accent)] [&_svg]:mt-0.5 [&_svg]:shrink-0", className)}>
      {icon}
      <span>
        <span className={cn(textVariants({ variant: "note" }), "block")}>{term}</span>
        <span className="block text-[length:var(--font-size-md)] leading-[1.3] font-semibold text-[var(--foreground)]">
          {children}
        </span>
      </span>
    </div>
  );
}

function Unit({ children }: { children: ReactNode }) {
  return <span className="text-[0.75em] font-normal text-[var(--color-muted)]">{children}</span>;
}

const PANEL_PROPS = {
  layer: "header",
  className: "w-76 max-w-[calc(100vw-2*var(--space-3))]",
  side: "bottom",
  align: "start",
} as const;
const MODEL_HEADING = "今日のモデルの計算値";

function PeriodSlot({ period }: { period: WeatherPeriodOutlook }) {
  return (
    <div className="flex w-10 flex-shrink-0 flex-col items-center gap-1 text-[var(--color-accent)]">
      <span className={cn(textVariants({ variant: "note" }), "tabular-nums")}>{formatPeriodLabel(period.period)}</span>
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
            aria-label="今日のモデルの計算値の取得に失敗しました"
          >
            今日
          </Button>
        </PopoverTrigger>
        <PopoverContent {...PANEL_PROPS}>
          <p className={cn(textVariants({ variant: "note" }), "mb-2 font-bold tracking-wide uppercase")}>
            {MODEL_HEADING}
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
  const {
    twilight,
    precipitation_max_mm: precipitationMax,
    wind_speed_max_ms: windSpeedMax,
    temperature_range: temperatureRange,
  } = weather;
  const stats = [
    precipitationMax != null && (
      <DailyStat key="precipitation" icon={<RaindropIcon size={15} />} term="降水量[最大]">
        {precipitationMax.toFixed(1)}
        <Unit>mm/h</Unit>
      </DailyStat>
    ),
    windSpeedMax != null && (
      <DailyStat key="wind" icon={<WindIcon size={15} />} term="風[最大]">
        {windSpeedMax.toFixed(1)}
        <Unit>m/s</Unit>
      </DailyStat>
    ),
    temperatureRange !== null && (
      <DailyStat key="temperature" icon={<ThermometerIcon size={15} />} term="気温">
        {`${Math.round(temperatureRange.min_c)}℃〜${Math.round(temperatureRange.max_c)}℃`}
      </DailyStat>
    ),
  ].filter(Boolean);
  const hasModelValue = stats.length > 0 || hasFlow;
  // キャッシュ欠落等でdaily側が丸ごと無い場合は、トグル自体を出さない
  // （空のパネルを開けるだけの無意味なボタンを残さない）。
  if (!hasModelValue && twilight === null) return null;

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          size="xs"
          shape="pill"
          className="bg-transparent font-semibold"
          aria-label="今日のモデルの計算値を表示"
          usage="今日の天気の見込み（気温・雨・風・日の出と日の入り）を開きます。"
        >
          今日
        </Button>
      </PopoverTrigger>
      <PopoverContent {...PANEL_PROPS}>
        {twilight !== null && (
          <DailyStat
            icon={<ClockIcon size={15} />}
            term="日の出・日没"
            className={hasModelValue ? "mb-2 border-b border-[var(--color-border)] pb-2" : undefined}
          >
            {formatClockTime(twilight.sunrise)}
            <Unit>〜</Unit>
            {formatClockTime(twilight.sunset)}
          </DailyStat>
        )}
        {hasModelValue && (
          <>
            <p className={cn(textVariants({ variant: "note" }), "font-bold tracking-wide uppercase")}>
              {MODEL_HEADING}
            </p>
            <p className={cn(textVariants({ variant: "note" }), "mb-2")}>
              気象庁の数値予報モデルMSMの計算値です。予報ではなく、誤差を含みえます。
            </p>
          </>
        )}
        <div className="grid grid-cols-2 gap-x-3 gap-y-2">{stats}</div>
        {hasFlow && (
          <div className="mt-2 border-t border-[var(--color-border)] pt-2">
            <p
              className={cn(textVariants({ variant: "note" }), "mb-1")}
            >{`${weather.today_period_interval_hours}時間ごと`}</p>
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
