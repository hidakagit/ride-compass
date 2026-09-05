"use client";

import * as Popover from "@radix-ui/react-popover";
import WindBearingSlider from "@/components/WindBearingSlider/WindBearingSlider";
import { WindDirectionArrowIcon } from "@/components/Map/icons";
import styles from "./TravelBearingControl.module.css";

interface TravelBearingControlProps {
  value: number;
  onChange: (bearingDeg: number) => void;
}

// 風・勾配で共有する走行方位（page.tsx: travelBearingDeg）を設定する唯一の入り口。
// MapLibreのズーム+/−・回転コントロール（地図右上、既定でmap.addControlされる）の
// すぐ下に置くことで、「地図の向き」と「走行方位（風・勾配の評価に使う向き）」という
// 別概念を並べて示す。サイズもズーム+/−コントロールと同じ29px四方に合わせてある
// （TravelBearingControl.module.css参照）。
//
// トリガーアイコンはWindBearingSlider.module.cssの`.dial`/`.arrow`と同じ配色・比率
// （矢印サイズ/ダイヤル直径≒0.65）を踏襲した「開く前のダイヤルのミニチュア」で、
// `value`に応じて矢印自体を回転させ、開く前から現在の走行方位が一目でわかるようにする。
// この矢印は実機の向き（ジャイロ/磁気センサー）とは一切連動しない、ユーザーがドラッグして
// 手動設定する値の表示専用。誤解防止のための説明文言は添えない——操作を妨げないことを
// 優先する。
const TRIGGER_ARROW_SIZE_PX = 18;

export default function TravelBearingControl({ value, onChange }: TravelBearingControlProps) {
  return (
    <Popover.Root>
      <Popover.Trigger asChild>
        <button type="button" className={styles.trigger} aria-label="走行方位を設定">
          <span
            aria-hidden="true"
            className={styles.triggerArrow}
            style={{ transform: `rotate(${value}deg)` }}
          >
            <WindDirectionArrowIcon size={TRIGGER_ARROW_SIZE_PX} />
          </span>
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content className={styles.popoverContent} side="left" align="start" sideOffset={8}>
          <WindBearingSlider value={value} onChange={onChange} ariaLabel="走行方位" />
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
