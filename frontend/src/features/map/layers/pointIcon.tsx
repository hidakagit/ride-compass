// 絵記号で描く点の絵（行の色の角丸四角に、白い絵記号を載せたもの）。地図へ登録する画素（`drawPointIcon`）と
// 凡例の見本（`PointIconSwatch`）は同じ形の宣言を読む——別々に描くと、凡例と地図の絵が食い違う。

import type { PointGlyph } from "@/lib/mapDisplay/legendFilter";
import { mapDisplay } from "@/types/generated/mapDisplay";
import palette from "@/types/generated/palette.json";

/** 形を書く座標の一辺（SVGのviewBoxと同じ単位）。画面での大きさは源泉の`iconSizePx`が決める。 */
const FRAME = 24;
const BOX_PATH = "M6 1h12a5 5 0 0 1 5 5v12a5 5 0 0 1-5 5H6a5 5 0 0 1-5-5V6a5 5 0 0 1 5-5Z";
/** 四角の縁取りは丸い点の縁取りと同じ画面上の太さにする。 */
const BOX_STROKE = (mapDisplay.point.strokeWidthPx * FRAME) / mapDisplay.point.iconSizePx;
/** 絵記号は四角の内側へ縮めて載せる。 */
const GLYPH_SCALE = 0.7;
const GLYPH_OFFSET = (FRAME * (1 - GLYPH_SCALE)) / 2;
const GLYPH_STROKE = 2;
/** 地図へ登録する画素の細かさ（画面の1pxあたり）。高精細の画面でも絵がにじまない。 */
const PIXEL_RATIO = 2;

/** 絵記号の線（`FRAME`の座標、線で描く）。 */
const GLYPH_PATHS: Record<PointGlyph, string> = {
  bag: "M6 9h12l-1 11H7Z M9 9V7.5a3 3 0 0 1 6 0V9",
  bottle: "M10 3h4 M10.5 3v3.5l-2 3V20a1 1 0 0 0 1 1h5a1 1 0 0 0 1-1V9.5l-2-3V3 M8.5 13h7",
  question: "M9 9a3 3 0 1 1 4.2 2.75c-.75.33-1.2 1-1.2 1.8V15 M12 19h.01",
  toilet: "M2.5 8l1.75 8L7 10l2.75 6L11.5 8 M21 9.5a4 4 0 1 0 0 5",
  drop: "M12 3c-3 4.5-6 7.5-6 11a6 6 0 0 0 12 0c0-3.5-3-6.5-6-11Z",
  parking: "M9 19V5h4.5a4 4 0 0 1 0 8H9",
};

/** 地図へ登録する絵。canvasの2D描画が使えなければ投げる——空の絵を返すと点が地図から消えるだけで誰も気づけない。 */
export function drawPointIcon(color: string, glyph: PointGlyph): { data: ImageData; pixelRatio: number } {
  const sizePx = mapDisplay.point.iconSizePx * PIXEL_RATIO;
  const canvas = document.createElement("canvas");
  canvas.width = sizePx;
  canvas.height = sizePx;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("canvasの2D描画が使えない");
  ctx.scale(sizePx / FRAME, sizePx / FRAME);
  const box = new Path2D(BOX_PATH);
  ctx.fillStyle = color;
  ctx.fill(box);
  ctx.strokeStyle = palette.semantic.mark_stroke;
  ctx.lineWidth = BOX_STROKE;
  ctx.stroke(box);
  ctx.translate(GLYPH_OFFSET, GLYPH_OFFSET);
  ctx.scale(GLYPH_SCALE, GLYPH_SCALE);
  ctx.strokeStyle = palette.semantic.mark_glyph;
  ctx.lineWidth = GLYPH_STROKE;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  ctx.stroke(new Path2D(GLYPH_PATHS[glyph]));
  return { data: ctx.getImageData(0, 0, sizePx, sizePx), pixelRatio: PIXEL_RATIO };
}

/** 凡例の見本。地図と同じ形・同じ大きさ。 */
export function PointIconSwatch({ color, glyph, className }: { color: string; glyph: PointGlyph; className?: string }) {
  const size = mapDisplay.point.iconSizePx;
  return (
    <svg aria-hidden="true" className={className} width={size} height={size} viewBox={`0 0 ${FRAME} ${FRAME}`}>
      <path d={BOX_PATH} fill={color} stroke={palette.semantic.mark_stroke} strokeWidth={BOX_STROKE} />
      <path
        d={GLYPH_PATHS[glyph]}
        transform={`translate(${GLYPH_OFFSET} ${GLYPH_OFFSET}) scale(${GLYPH_SCALE})`}
        fill="none"
        stroke={palette.semantic.mark_glyph}
        strokeWidth={GLYPH_STROKE}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
