"use client";

import { useState } from "react";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/Popover/Popover";
import { Button } from "@/components/ui/Button/Button";
import { ClearAllFiltersIcon, ClearAllLayersIcon, RedrawMapIcon, ResetMapIcon } from "@/components/ui/icons/icons";

interface MapResetMenuProps {
  anyLayerOn: boolean;
  hideAllLayers: () => void;
  anyLegendHidden: boolean;
  showAllLegendRows: () => void;
  redraw: () => void;
}

// 地図の表示を「まとめて元に戻す」操作を、地図の右の列の1つのボタンから開くメニューに並べる。
export default function MapResetMenu({
  anyLayerOn,
  hideAllLayers,
  anyLegendHidden,
  showAllLegendRows,
  redraw,
}: MapResetMenuProps) {
  const [open, setOpen] = useState(false);
  // 押したらメニューを閉じる（開いたままだと、戻した地図の上にメニューが残る）。
  const run = (action: () => void) => () => {
    action();
    setOpen(false);
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="mapCtrl"
          size="mapCtrl"
          aria-label="まとめて戻す"
          usage="地図の表示をまとめて元に戻す操作を開きます。"
        >
          <ResetMapIcon />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="flex min-w-56 flex-col gap-1 p-1.5" side="left" align="start" sideOffset={8}>
        <Button
          variant="menu"
          size="sm"
          onClick={run(hideAllLayers)}
          disabled={!anyLayerOn}
          usage="地図の左のチップでONにした表示を、まとめてOFFにします。"
        >
          <ClearAllLayersIcon size={15} />
          表示中のレイヤーをすべて非表示
        </Button>
        <Button
          variant="menu"
          size="sm"
          onClick={run(showAllLegendRows)}
          disabled={!anyLegendHidden}
          usage="凡例のチェックを外して隠した段階を、まとめて地図に戻します。"
        >
          <ClearAllFiltersIcon size={15} />
          絞り込みをすべて解除
        </Button>
        {/* 押した人の地図だけを描き直す（ページを読み込み直すと生成したルートが消える）。 */}
        <Button
          variant="menu"
          size="sm"
          onClick={run(redraw)}
          usage="地図の表示が欠けたときに、地図だけを描き直します。作ったルートは消えません。"
        >
          <RedrawMapIcon size={15} />
          地図の表示を再描画
        </Button>
      </PopoverContent>
    </Popover>
  );
}
