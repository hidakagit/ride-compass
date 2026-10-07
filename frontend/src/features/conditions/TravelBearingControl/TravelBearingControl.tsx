"use client";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/Popover/Popover";
import WindBearingSlider from "@/features/conditions/WindBearingSlider/WindBearingSlider";
import { WindDirectionArrowIcon } from "@/components/ui/icons/icons";
import { Button } from "@/components/ui/Button/Button";
import { mapOverlayEdge } from "@/lib/mapOverlayEdges";
import { useAxisCatalog } from "@/hooks/useAxisCatalog";
import { axisNamesUsing } from "@/lib/catalogAxis";

interface TravelBearingControlProps {
  value: number;
  onChange: (bearingDeg: number) => void;
}

// 向きで値の変わる評価が共有する走行方位（`features/conditions/useRideConditions.ts: bearingDeg`）を設定する唯一の入り口。
// MapLibreのズーム+/−・回転コントロール（地図右上、既定でmap.addControlされる）の
// すぐ下に置くことで、「地図の向き」と「走行方位（向きで値の変わる評価に使う向き）」という
// 別概念を並べて示す。幅・高さ・アイコンの大きさは右上の列の共通値
// （globals.css: --map-ctrl-*）に合わせてある。
//
// トリガーアイコンは風向ダイヤル（WindBearingSlider）と同じ配色・比率
// （矢印サイズ/ダイヤル直径≒0.65）を踏襲した「開く前のダイヤルのミニチュア」で、
// `value`に応じて矢印自体を回転させ、開く前から現在の走行方位が一目でわかるようにする。
// この矢印は実機の向き（ジャイロ/磁気センサー）とは一切連動しない、ユーザーがドラッグして
// 手動設定する値の表示専用。誤解防止のための説明文言は添えない——操作を妨げないことを
// 優先する。
export default function TravelBearingControl({ value, onChange }: TravelBearingControlProps) {
  // 向きで値の変わる評価の名前は軸カタログから引く。無ければ評価に触れる文を出さない。
  const bearingAxes = axisNamesUsing(useAxisCatalog().axes, "bearing_deg");
  const evaluationUsage = bearingAxes
    ? `${bearingAxes}で周りの道を色分けするときと、道の評価を見るときの走る向きを決めます。ルートの評価は、ルートを実際に走る向きで決まります。`
    : "";
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          variant="mapCtrl"
          size="mapCtrl"
          className="absolute top-[var(--map-ctrl-stack-top)] right-[var(--map-ctrl-margin)] z-[var(--z-map-control)]"
          aria-label="走行方位を設定"
          usage={`${evaluationUsage}地図や端末の向きとは連動しません。`}
          {...mapOverlayEdge("right")}
        >
          <span
            aria-hidden="true"
            className="inline-flex items-center justify-center transition-transform duration-50 ease-linear"
            style={{ transform: `rotate(${value}deg)` }}
          >
            <WindDirectionArrowIcon />
          </span>
        </Button>
      </PopoverTrigger>
      <PopoverContent className="p-2" side="left" align="start" sideOffset={8}>
        <div className="contents" data-usage="ダイヤルを回して、走る向きを決めます。">
          <WindBearingSlider value={value} onChange={onChange} ariaLabel="走行方位" />
        </div>
      </PopoverContent>
    </Popover>
  );
}
