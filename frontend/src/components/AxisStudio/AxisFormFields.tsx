"use client";

// 軸スタジオのフォームが共有する小さな入力部品。節ごとのファイル（AxisComposer.tsx・
// AxisScoringSection.tsx・AxisMapDisplaySection.tsx）から使う。見た目は
// docs/modules/frontend/frontend-design-system.mdのトークンに従い、説明文は地の文ではなく(ⓘ)に畳む。

import InfoPopover from "@/components/Map/InfoPopover";
import { type AxisMaterialOption } from "@/lib/axisMaterialsCatalog";
import { NumberInput } from "@/components/ui/NumberInput/NumberInput";
import { textVariants } from "@/components/ui/Text/Text";

/** 材料選択セレクトの隣に置く情報アイコン(ⓘ)。選択中の材料の説明文
 * （backend/app/domain/material_catalog.py: MaterialSpec.description）をポップオーバーで
 * 表示する。材料が複数行並ぶ欄（terms/flags）でも行ごとに選択中の材料が違うため、
 * FieldLabelをそのまま流用せずラベル文言を持たない専用の小型トリガーにする（行ごとに
 * 毎回同じ文言を繰り返し表示すると煩雑なため）。 */
export function InfoPopoverButton({ ariaLabel, description }: { ariaLabel: string; description: string }) {
  return <InfoPopover triggerAriaLabel={ariaLabel}>{description}</InfoPopover>;
}

export function MaterialInfoButton({ option }: { option: AxisMaterialOption | undefined }) {
  if (!option) return null;
  return <InfoPopoverButton ariaLabel={`${option.label}の説明`} description={option.description} />;
}

/** 見出し＋詳しい説明は(ⓘ)ポップオーバーへ折りたたむ（表示名・既定重み欄で既に使っている
 * FieldLabelと同じ考え方を、フォーム項目1つではなく材料一覧・折れ点等のセクション
 * 単位に広げたもの）。descriptionを省略した場合は見出しだけを出す。 */
export function SectionLabel({ label, description }: { label: string; description?: string }) {
  return (
    <div className="flex items-center gap-1">
      <p className={textVariants({ variant: "label" })}>{label}</p>
      {description && <InfoPopoverButton ariaLabel={`${label}の説明`} description={description} />}
    </div>
  );
}

/** 係数・スコアの入力を「スライダーで大まかに調整＋数値で正確に入力」の組み合わせに
 * する。両者は同じstateを指すため常に同期する。値そのものの取りうる範囲は材料ごとに
 * 大きく異なる（傾斜の係数1.0、車線数の係数0.1等）ため、スライダーの範囲はあくまで
 * 「大まかな調整用の目安」とし、範囲外の値は数値入力欄から直接指定できる（スライダー
 * 自体はその値を表示できないが、隣の数値入力の値がそのまま送信される）。 */
export function SliderNumberField({
  value,
  onChange,
  label,
  min,
  max,
  step,
}: {
  value: number;
  onChange: (next: number) => void;
  label: string;
  min: number;
  max: number;
  step: number;
}) {
  const clamped = Math.min(max, Math.max(min, value));
  return (
    <span className="inline-flex items-center gap-2 [&_input[type=number]]:w-18 [&_input[type=range]]:w-48">
      <input
        type="range"
        aria-label={`${label}(スライダー)`}
        min={min}
        max={max}
        step={step}
        value={clamped}
        onChange={(e) => onChange(Number(e.target.value))}
      />
      {/* スライダー側は刻みを持つが、数値欄は`step="any"`にする。固定の刻みは浮動小数の
          誤差で制約検証に引っかかり（0.1が step="0.01" の倍数と見なされない）、同じ画面の
          他の欄を保存しようとしたときにフォーム送信ごと黙って止まる。 */}
      <NumberInput commitOn="input" value={value} onValueChange={onChange} step="any" aria-label={label} />
    </span>
  );
}
