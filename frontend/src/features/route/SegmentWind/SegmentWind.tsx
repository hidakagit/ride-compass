import InfoPopover from "@/components/ui/InfoPopover/InfoPopover";
import { textVariants } from "@/components/ui/Text/Text";
import { cardinalLabel } from "@/features/conditions/cardinalLabel";
import { cn } from "@/lib/cn";
import routeGenerateConfig from "@/types/generated/route-generate-config.json";
import type { RouteSegmentDetail } from "@/types/route";

const HOURS_PER_LEG = routeGenerateConfig.wind_forecast_hours_per_leg;

/** 区間の評価に使った風。どの時刻の予報を使ったかと、予報を追える範囲の先で延ばして使ったかを出す——出さないと、
 * 地図の矢印（選んだ時刻の地点ごとの予報）やヘッダーの風（今の観測）と見比べて食い違って見える。 */
export default function SegmentWind({ wind }: { wind: RouteSegmentDetail["wind"] }) {
  // backendより先にこの画面が出ると、応答に`wind`が無い（undefined）。
  if (wind == null) return null;
  const when = wind.forecast_at == null ? "出発時点の風" : `${wind.forecast_at.slice(11, 16)}の予報`;
  return (
    <p className={cn(textVariants({ variant: "hint" }), "m-0 inline-flex flex-wrap items-baseline gap-x-1")}>
      <span>
        風 {when}・{cardinalLabel(wind.direction_deg)}の風 {wind.speed_ms.toFixed(1)}m/s
      </span>
      {wind.extended && <span>（予報の先を延ばして使用）</span>}
      <InfoPopover triggerAriaLabel="区間の風の説明">
        <p>
          この区間を通る見込みの時刻の、その場所に最も近い予報の格子点の風（1時間刻み）で評価しています。往路・復路それぞれ、走り始めてから
          {HOURS_PER_LEG}
          時間先までを追い、その先の区間は最後に追った時刻の予報をそのまま使います（「予報の先を延ばして使用」と出ます）。
        </p>
      </InfoPopover>
    </p>
  );
}
