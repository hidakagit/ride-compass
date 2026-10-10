// 地図の記号に使う単色シルエットのCanvas 2D描画。どの絵も`sdf: true`で登録し、色は
// icon-colorで付けるため、塗りは白で固定する。

/** 1辺`sizePx`の正方形に`draw`で描いた絵を、MapLibreへ渡す画素にする。canvasの2D描画が使えなければ投げる。 */
export function drawCanvasIcon(sizePx: number, draw: (ctx: CanvasRenderingContext2D) => void): ImageData {
  const canvas = document.createElement("canvas");
  canvas.width = sizePx;
  canvas.height = sizePx;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("canvasの2D描画が使えない");
  draw(ctx);
  return ctx.getImageData(0, 0, sizePx, sizePx);
}

/** 白で塗る単色シルエット（`drawCanvasIcon`の塗りを白に決めたもの）。 */
export function drawSdfIcon(sizePx: number, draw: (ctx: CanvasRenderingContext2D) => void): ImageData {
  return drawCanvasIcon(sizePx, (ctx) => {
    ctx.fillStyle = "#ffffff";
    draw(ctx);
  });
}
