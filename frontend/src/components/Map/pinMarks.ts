import palette from "@/types/generated/palette.json";
import type { PinRole } from "@/types/route";

// 地点（出発地・経由地・目的地）の印。**地図のピンと、ルート設定パネルの行の印は同じ図形**
// ——行とピンが同じものを指していることを、色と形だけで読めるようにする。
//
// 地図側はMapLibreのMarkerへ渡す生のDOMを組み立てるためReact要素を使えない。両方から使える
// 唯一の形として、印の中身をHTML文字列で持つ（差し込む値はこのモジュール内の定数と経由地の
// 番号だけで、外部の入力は入らない）。

export const PIN_MARK_BACKGROUND: Record<PinRole, string> = {
  // 出発地は白いバッジの中に十字を描く（地図の上でも「現在地」の慣習的な見た目になる）。
  origin: palette.semantic.pin_origin_background,
  waypoint: palette.semantic.pin_waypoint,
  destination: palette.semantic.pin_destination,
};

/** 出発地の十字（中身の色は呼び出し側が決める——位置が未取得の間は灰色にする）。 */
export const ORIGIN_MARK_COLOR = palette.semantic.pin_origin;
export const ORIGIN_MARK_FALLBACK_COLOR = palette.semantic.pin_origin_unresolved;

function originCrosshairSvg(size: number, color: string): string {
  return (
    `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" aria-hidden="true">` +
    `<circle cx="12" cy="12" r="3" fill="${color}" />` +
    `<path d="M12 2v3M12 19v3M2 12h3M19 12h3M12 6a6 6 0 1 0 0 12 6 6 0 0 0 0-12Z" ` +
    `stroke="${color}" stroke-width="2" stroke-linecap="round" />` +
    `</svg>`
  );
}

interface PinMarkOptions {
  /** 経由地の中に出す番号（地図は訪問順、パネルの行は件数）。 */
  label?: string;
  /** 出発地の十字の大きさ（px）。 */
  size?: number;
  /** 出発地の十字の色（位置が未取得の間は灰色）。 */
  color?: string;
}

/** 印の中身（HTML文字列）。地図のピンとパネルの行が同じものを使う。 */
export function pinMarkHtml(
  role: PinRole,
  { label, size = 20, color = ORIGIN_MARK_COLOR }: PinMarkOptions = {},
): string {
  if (role === "origin") return originCrosshairSvg(size, color);
  if (role === "destination") return "⚑";
  return label ?? "";
}
