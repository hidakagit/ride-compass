"use client";

import * as Popover from "@radix-ui/react-popover";
import WindBearingSlider from "@/components/WindBearingSlider/WindBearingSlider";
import { WindDirectionArrowIcon } from "@/components/Map/icons";
import styles from "./TravelBearingControl.module.css";

interface TravelBearingControlProps {
  value: number;
  onChange: (bearingDeg: number) => void;
}

// ユーザー要望（2026-08-31、「今は軸毎やレイヤ毎に走行方位が決められるけれど、1つでいい。
// 地図上の色＋−方角アイコンの下にコンパスアイコン設けて、そこから今の走行方位を開いて
// 設定できない？」）: 風・勾配それぞれ個別に持っていたコンパス（環境グループの地図下部・
// RouteSettingsPanel内の「走行方位を設定」）を1つの共有値（page.tsx: travelBearingDeg）・
// 1つの入り口（この地図上アイコン）へ集約した。MapLibreのズーム+/−・回転コントロール
// （地図右上、既定でmap.addControlされる）のすぐ下に置く——ユーザーが名指しした
// 「色＋−方角アイコン」（ズーム+/−・地図の回転/方位アイコン）と同じ並びに置くことで
// 「地図の向き」と「走行方位（風・勾配の評価に使う向き）」という別概念を並べて示す。
export default function TravelBearingControl({ value, onChange }: TravelBearingControlProps) {
  return (
    <Popover.Root>
      <Popover.Trigger asChild>
        <button type="button" className={styles.trigger} aria-label="走行方位を設定">
          <WindDirectionArrowIcon size={18} />
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
