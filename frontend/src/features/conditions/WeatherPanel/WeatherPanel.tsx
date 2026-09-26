import { RaindropIcon, ThermometerIcon, WindDirectionArrowIcon } from "@/components/ui/icons/icons";
import type { AmedasObservation } from "@/types/weather";
import { getAmedasWeatherDisplay } from "./amedasWeatherIcon";
import { textVariants } from "@/components/ui/Text/Text";

interface WeatherPanelProps {
  amedas: AmedasObservation | null;
  loading: boolean;
  error: string | null;
}

// 常設ヘッダーは予報ではなく最寄りアメダス観測所の実測値のみで構成する。
// TodayOutlook（今日の見通し、MSM予報）とは独立にフェッチするため、予報側の
// 障害・遅延から表示が影響を受けない。
//
// アメダスは観測専用APIのため、降水確率・weather_code（予報由来）はそのままでは
// 表示できない。代わりに:
// - 降水確率 → 実測の10分間降水量（precipitation_10min_mm）
// - 天気アイコン → backendが10分間日照時間・降水量・気温から導いた天気コード（weather_code）
// - 突風 → アメダスの速報値レスポンスに突風フィールドが存在しないため非表示
//
// 日の出/日没は1日1個の値のため、このバーではなく「今日」パネル（TodayOutlook）が持つ
// ——バーは走行中に何度も見る瞬間値だけに絞る。
function isCurrentlyDay(sunrise: string | null, sunset: string | null): boolean {
  if (sunrise == null || sunset == null) return true;
  const now = Date.now();
  return now >= new Date(sunrise).getTime() && now < new Date(sunset).getTime();
}

export default function WeatherPanel({ amedas, loading, error }: WeatherPanelProps) {
  // 手元に観測値があるなら、直近の取り直しが失敗していてもそちらを出す（失敗の文言で
  // 値を置き換えない）。取得は一定間隔で続くため、回復すれば表示も戻る。
  if (!amedas) {
    if (loading) return <p className={textVariants({ variant: "hint" })}>天候取得中...</p>;
    // backendは観測所の解決失敗・欠測・上流の取得失敗を区別せず502にするため、「無い」と
    // 断定せず取得できなかったことだけを出す。原因の詳細（混雑・HTTPステータス等）はtitleへ回す。
    if (error)
      return (
        <p className={textVariants({ variant: "error" })} title={error}>
          観測値を取得できません
        </p>
      );
    return null;
  }

  const temperatureTitle =
    amedas.apparent_temperature_c != null ? `体感 ${amedas.apparent_temperature_c.toFixed(1)}℃` : undefined;
  const windTitle = amedas.wind_direction_label != null ? `${amedas.wind_direction_label}の風` : undefined;

  const weatherDisplay = getAmedasWeatherDisplay(amedas.weather_code, isCurrentlyDay(amedas.sunrise, amedas.sunset));

  return (
    // 気温・風向風速・降水量・天気アイコンをアイコン+数値だけの統計チップとして1行に並べる
    // （はみ出した分は横へ流し、ヘッダーを2行にしない）。
    <div className="flex flex-nowrap items-center gap-2 overflow-x-auto text-[var(--foreground)] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden [&_svg]:shrink-0">
      <span
        className="inline-flex flex-shrink-0 items-center gap-1 whitespace-nowrap text-[length:var(--font-size-md)] font-semibold"
        title={temperatureTitle}
      >
        <ThermometerIcon size={16} />
        <span className="sr-only">気温: </span>
        {/* 数値と単位は1つのspanにまとめて.statのgapが間に入らないようにする
            （flexboxのgapは直接の子要素すべての間に均等に効くため、数値と単位を別々の
            子要素のままにすると、アイコン↔数値と同じ間隔が数値↔単位にも入ってしまい
            意図しない余白になる）。 */}
        <span>
          {amedas.temperature_c != null ? amedas.temperature_c.toFixed(1) : "-"}
          <span className="text-[0.8em] font-normal text-[var(--color-muted)]">℃</span>
        </span>
      </span>

      <span className="w-px flex-shrink-0 self-stretch bg-[var(--color-border)]" aria-hidden="true" />

      {amedas.wind_speed_ms != null && amedas.wind_direction_deg != null && (
        <span
          className="inline-flex flex-shrink-0 items-center gap-1 whitespace-nowrap text-[length:var(--font-size-md)] font-semibold"
          title={windTitle}
        >
          <span
            className="inline-flex transition-transform duration-200"
            style={{ transform: `rotate(${amedas.wind_direction_deg + 180}deg)` }}
          >
            <WindDirectionArrowIcon size={16} />
          </span>
          <span className="sr-only">{amedas.wind_direction_label}の風: </span>
          <span>
            {amedas.wind_speed_ms.toFixed(1)}
            <span className="text-[0.8em] font-normal text-[var(--color-muted)]">m/s</span>
          </span>
        </span>
      )}

      {amedas.precipitation_10min_mm != null && (
        <>
          <span className="w-px flex-shrink-0 self-stretch bg-[var(--color-border)]" aria-hidden="true" />
          <span
            className="inline-flex flex-shrink-0 items-center gap-1 whitespace-nowrap text-[length:var(--font-size-md)] font-semibold"
            title="直近10分間の降水量"
          >
            <RaindropIcon size={16} />
            <span className="sr-only">降水量: </span>
            <span>
              {amedas.precipitation_10min_mm.toFixed(1)}
              <span className="text-[0.8em] font-normal text-[var(--color-muted)]">mm</span>
            </span>
          </span>
        </>
      )}

      {weatherDisplay != null && (
        <>
          <span className="w-px flex-shrink-0 self-stretch bg-[var(--color-border)]" aria-hidden="true" />
          <span
            className="inline-flex flex-shrink-0 items-center gap-1 whitespace-nowrap text-[length:var(--font-size-md)] font-semibold"
            title={weatherDisplay.label}
          >
            <weatherDisplay.Icon size={16} />
            <span className="sr-only">天気: {weatherDisplay.label}</span>
          </span>
        </>
      )}
    </div>
  );
}
