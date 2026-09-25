// 軸のアイコンの固定のパレット（軸自身の`icon_id`→アイコン）。軸スタジオは選ぶだけで、形を足すにはここへ1件足す
// （任意のSVGの登録は意匠の揃いと無害化の費用が高く、頭文字の自動生成は形で意味が伝わる性質を失う）。
// 知らない・未設定の`icon_id`は汎用のアイコンにする。

import {
  AccidentDensityAxisIcon,
  AxisRampIcon,
  ClockIcon,
  WarningTriangleIcon,
  GradientAxisIcon,
  LayersStackIcon,
  NightAxisIcon,
  ShieldIcon,
  StopDensityAxisIcon,
  SurfaceQualityAxisIcon,
  TargetIcon,
  ThermometerIcon,
  WindIcon,
  type MapIconComponent,
} from "@/components/ui/icons/icons";

type AxisIconComponent = MapIconComponent;

interface AxisIconPaletteEntry {
  /** パレット選択UI（AxisComposer.tsx）に出す短い名前。 */
  label: string;
  Icon: AxisIconComponent;
}

// キー（icon_id）は形の名前にし、軸idに紐付けない（同じ形を複数の軸が選べる）。
export const AXIS_ICON_PALETTE: Record<string, AxisIconPaletteEntry> = {
  incline: { label: "傾斜線（勾配）", Icon: GradientAxisIcon },
  wave: { label: "波線（路面・質）", Icon: SurfaceQualityAxisIcon },
  "crescent-moon": { label: "三日月（夜間）", Icon: NightAxisIcon },
  "density-stack": { label: "積み上がる点（密度・縦）", Icon: StopDensityAxisIcon },
  "density-scatter": { label: "散らばる点（密度・分布）", Icon: AccidentDensityAxisIcon },
  "warning-triangle": { label: "警告三角（リスク・注意）", Icon: WarningTriangleIcon },
  "wind-flow": { label: "風（渦・流れ）", Icon: WindIcon },
  thermometer: { label: "温度計", Icon: ThermometerIcon },
  shield: { label: "盾（安全・保護）", Icon: ShieldIcon },
  target: { label: "的（精度）", Icon: TargetIcon },
  clock: { label: "時計（時間）", Icon: ClockIcon },
  layers: { label: "積層（複合指標）", Icon: LayersStackIcon },
};

/** icon_idからアイコンコンポーネントを引く。未知/未設定はAxisRampIcon（汎用フォールバック）。 */
export function axisIconFor(iconId: string | null | undefined): AxisIconComponent {
  if (iconId == null) return AxisRampIcon;
  return AXIS_ICON_PALETTE[iconId]?.Icon ?? AxisRampIcon;
}
