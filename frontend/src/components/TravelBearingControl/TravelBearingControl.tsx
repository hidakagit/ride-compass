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
// ユーザー指摘（2026-08-31、「アイコンが非常に見にくい。丸形の中にすごく小さく矢印。
// これを、コンパス設定画面をそのまま縮小したみたいにはできない？」）: 従来は現在値を
// 反映しない固定の矢印アイコン（常に北向きのまま回転しない）だったため、(1)向きの
// プレビューとして機能していない、(2)アイコン自体が小さく視認しづらい、の2点を指摘された。
// WindBearingSlider.module.cssの`.dial`/`.arrow`と同じ配色・比率（矢印サイズ/ダイヤル直径
// ≒0.65）を踏襲した「開く前のダイヤルのミニチュア」として再設計し、`value`に応じて
// 矢印自体を回転させることで開く前から現在の走行方位が一目でわかるようにした。
//
// ユーザー指摘（2026-08-31、「アイコンの矢印が北向き（上）固定に見えてるけど、これスマホの
// 向いている方角と連動させたってこと？」）: この矢印は実機の向き（ジャイロ/磁気センサー）
// とは一切連動しない、ユーザーがドラッグして手動設定する値の表示専用（ユーザー選定:
// 実機連動はせず手動設定のまま）。ポップオーバーに説明文を添える対応を一度試みたが、
// 「説明文言は邪魔」という指摘で撤回した——誤解防止より前に、まず操作を妨げない
// ことを優先する。再度この種の説明文を足す前に本コメントを参照すること。
//
// ユーザー指摘（2026-08-31、「アイコンのデザインを補正。他ボタン、＋、−等と同じ感じに
// できない？」）を受け、MapLibreのズーム+/−コントロールと同じ29px四方に合わせた
// （TravelBearingControl.module.css参照）。矢印サイズもその中に収まる比率へ縮小した。
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
