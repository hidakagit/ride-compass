import InfoPopover from "@/components/ui/InfoPopover/InfoPopover";
import { textVariants } from "@/components/ui/Text/Text";
import { cardinalLabel } from "@/lib/cardinalLabel";
import { cn } from "@/lib/cn";
import { formatJstHourMinute, parseJstLocalValue } from "@/lib/time";
import routeGenerateConfig from "@/types/generated/route-generate-config.json";
import type { RouteSegmentDetail } from "@/types/route";

const HOURS_PER_LEG = routeGenerateConfig.wind_forecast_hours_per_leg;

/** 区間の評価に使った風。どの時刻の値を使ったかと、追える時刻の先で延ばして使ったかを出す——出さないと、
 * 地図の矢印（選んだ時刻の地点ごとの値）やヘッダーの風（今の観測）と見比べて食い違って見える。
 * 値は数値予報モデルの計算値で、「予報」と呼ばない（docs/architecture/data-sources.md「気象業務法の予報業務許可」節）。 */
export default function SegmentWind({ wind }: { wind: RouteSegmentDetail["wind"] }) {
  // backendより先にこの画面が出ると、応答に`wind`が無い（undefined）。
  if (wind == null) return null;
  const when =
    wind.forecast_at == null
      ? "出発時点の風"
      : `${formatJstHourMinute(parseJstLocalValue(wind.forecast_at))}のモデルの計算値`;
  return (
    <p className={cn(textVariants({ variant: "hint" }), "m-0 inline-flex flex-wrap items-baseline gap-x-1")}>
      <span>
        {when}: {cardinalLabel(wind.direction_deg)} {wind.speed_ms.toFixed(1)}m/s
      </span>
      {wind.extended && <span>[延長]</span>}
      <InfoPopover triggerAriaLabel="区間の風の説明">
        <p>
          この区間を通る見込みの時刻の、その場所に最も近い格子点の風[気象庁の数値予報モデルMSMの計算値、1時間刻み]で評価しています。
          予報ではなく、誤差を含みえます。往路・復路それぞれ、走り始めてから
          {HOURS_PER_LEG}
          時間先までを追い、その先の区間は最後に追った時刻の値をそのまま使います[「延長」と出ます]。
        </p>
      </InfoPopover>
    </p>
  );
}
