// 雷放電位置データ（liden、改善計画T541）の地図上マーカーアイコンのCanvas 2D描画。
// windArrowIcon.tsと同じ「MapLibre/DOM以外に依存しない純粋な幾何計算」の方針で分離する。

const LIDEN_ICON_SIZE_PX = 24;

/** 単体の稲妻シルエット（icons.tsx: LidenIconと同じ形をCanvas 2Dで描いたもの）。
 * `sdf: true`で登録し、icon-colorで着色する（windArrowIcon.tsと同じ使い方）。 */
export function createLidenIcon(): ImageData {
  const canvas = document.createElement("canvas");
  canvas.width = LIDEN_ICON_SIZE_PX;
  canvas.height = LIDEN_ICON_SIZE_PX;
  const ctx = canvas.getContext("2d");
  if (!ctx) return new ImageData(LIDEN_ICON_SIZE_PX, LIDEN_ICON_SIZE_PX);
  ctx.fillStyle = "#ffffff";

  ctx.beginPath();
  ctx.moveTo(13, 2);
  ctx.lineTo(6, 14);
  ctx.lineTo(11, 14);
  ctx.lineTo(9, 22);
  ctx.lineTo(18, 9.5);
  ctx.lineTo(12.5, 9.5);
  ctx.closePath();
  ctx.fill();

  return ctx.getImageData(0, 0, LIDEN_ICON_SIZE_PX, LIDEN_ICON_SIZE_PX);
}
