// 雷放電位置データ（liden）の地図上マーカーアイコン。

import { drawSdfIcon } from "@/features/map/layers/sdfIcon";

const LIDEN_ICON_SIZE_PX = 24;

/** 単体の稲妻シルエット。 */
export function createLidenIcon(): ImageData {
  return drawSdfIcon(LIDEN_ICON_SIZE_PX, (ctx) => {
    ctx.beginPath();
    ctx.moveTo(13, 2);
    ctx.lineTo(6, 14);
    ctx.lineTo(11, 14);
    ctx.lineTo(9, 22);
    ctx.lineTo(18, 9.5);
    ctx.lineTo(12.5, 9.5);
    ctx.closePath();
    ctx.fill();
  });
}
