// 軸の地図チップアイコンの固定パレット（改善計画T310）。
//
// 以前は既存6軸限定の`SECONDARY_AXIS_ICONS`（軸id→アイコンの手書き辞書、
// MapOverlayControls.tsx）が存在し、軸スタジオで新規作成した軸は常に汎用の
// `AxisRampIcon`にフォールバックしていた（既存軸だけの特別扱い）。
//
// T310でこの辞書を撤去し、`icon_id`（`AXIS_DEFINITIONS`/軸スタジオが軸自身のデータとして
// 持つ、backend/app/domain/axis_definitions.py: AxisDefinition.icon_id）→アイコン
// コンポーネントというフラットなパレット参照へ置き換えた。これにより既存軸・GUI作成軸の
// どちらも同じ経路（軸自身のicon_idを持つ→ここで引く）でアイコンが決まる。
//
// アイコン形状の登録方式はユーザー判断（2026-08-25）: 「デフォルトでアイコンを色々
// 用意しておきそこから選ぶ形にして。必要に応じて都度アイコン追加をモジュール改修で対応
// する」——GUIからの任意SVG登録（スタイル一貫性・XSSサニタイズのコストが高い）や
// ラベル頭文字からのモノグラム自動生成（既存の手描きアイコンが持つ「形だけで意味が伝わる」
// 性質を失う）は見送り、固定パレットから選ぶ方式を採用した。新しいアイコン形状の追加は
// 引き続きこのファイルへの1件追加＋コード変更を要する（軸スタジオ側はicon_idを選ぶだけ）。
// 未知/未設定のicon_idはAxisRampIcon（汎用フォールバック）へ倒す——パレットに無い値でも
// 動作は壊れない。

import type { ReactElement } from "react";
import {
  AccidentDensityAxisIcon,
  AxisRampIcon,
  ClockIcon,
  CarStressIcon,
  GradientAxisIcon,
  LayersStackIcon,
  NightAxisIcon,
  ShieldIcon,
  StopDensityAxisIcon,
  SurfaceQualityAxisIcon,
  TargetIcon,
  ThermometerIcon,
  WindIcon,
} from "./icons";

export type AxisIconComponent = (props: { size?: number }) => ReactElement;

interface AxisIconPaletteEntry {
  /** パレット選択UI（AxisComposer.tsx）に出す短い名前。 */
  label: string;
  Icon: AxisIconComponent;
}

// 既存6軸（改善計画T166確定命名表）が使っていた意匠 + 新規軸向けのスペア（ユーザー指示
// 「色々用意しておき」への対応）。キー（icon_id）は形状の説明的な名前とし、特定の軸idに
// 紐付けない（同じ形状を複数の軸が選べる、パレットの性質上当然の設計）。
export const AXIS_ICON_PALETTE: Record<string, AxisIconPaletteEntry> = {
  incline: { label: "傾斜線（勾配）", Icon: GradientAxisIcon },
  wave: { label: "波線（路面・質）", Icon: SurfaceQualityAxisIcon },
  "crescent-moon": { label: "三日月（夜間）", Icon: NightAxisIcon },
  "density-stack": { label: "積み上がる点（密度・縦）", Icon: StopDensityAxisIcon },
  "density-scatter": { label: "散らばる点（密度・分布）", Icon: AccidentDensityAxisIcon },
  "warning-triangle": { label: "警告三角（リスク・注意）", Icon: CarStressIcon },
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
