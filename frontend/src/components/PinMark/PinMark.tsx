import { LocateIcon } from "@/components/ui/icons/icons";
import palette from "@/types/generated/palette.json";
import type { PinRole } from "@/types/route";

// 地点（出発地・経由地・目的地）の印。**地図のピンと、ルート設定パネルの地点の印は同じ図形**
// ——パネルとピンが同じものを指していることを、色と形だけで読めるようにする。

export const PIN_MARK_BACKGROUND: Record<PinRole, string> = {
  // 出発地は面の色のバッジの中に現在地の印を描く。面はテーマに従う（ダークなら暗い台）ので、配信された1つの値ではなく
  // CSSのトークンを読む（`lib/paletteCssVariables.ts`の決まり）。
  origin: "var(--color-surface)",
  waypoint: palette.semantic.pin_waypoint,
  destination: palette.semantic.pin_destination,
};

/** 出発地の印の色（位置が未取得の間は灰色にする）。 */
export const ORIGIN_MARK_COLOR = palette.semantic.pin_origin;
export const ORIGIN_MARK_FALLBACK_COLOR = palette.semantic.pin_origin_unresolved;

interface PinMarkProps {
  role: PinRole;
  /** 経由地の中に出す番号（地図もパネルも訪問の順）。 */
  label?: string;
  /** 出発地の印の大きさ（px）。 */
  size: number;
  /** 出発地の印の色。 */
  color?: string;
}

/** 経由地・目的地の印は文字だけなので、地図のピンはこれを要素の文字として入れる。 */
export function pinMarkText(role: Exclude<PinRole, "origin">, label: string | undefined): string {
  return role === "destination" ? "⚑" : (label ?? "");
}

/** 印の中身。パネルの地点と、地図の出発地のピン（Markerの要素へportalで差し込む）が使う。 */
export function PinMark({ role, label, size, color = ORIGIN_MARK_COLOR }: PinMarkProps) {
  if (role !== "origin") return pinMarkText(role, label);
  return (
    <span className="inline-flex" style={{ color }}>
      <LocateIcon size={size} />
    </span>
  );
}
