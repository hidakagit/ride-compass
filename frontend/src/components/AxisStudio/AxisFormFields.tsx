"use client";

// 軸スタジオのフォームが共有する小さな入力部品。節ごとのファイル（AxisComposer.tsx・
// AxisScoringSection.tsx・AxisMapDisplaySection.tsx）から使う。見た目は
// docs/frontend-design-system.mdのトークンに従い、説明文は地の文ではなく(ⓘ)に畳む。

import { useState } from "react";
import InfoPopover from "@/components/Map/InfoPopover";
import { type AxisMaterialOption } from "@/lib/axisMaterialsCatalog";
import styles from "./AxisStudio.module.css";
import infoButtonStyles from "@/components/ui/infoButton.module.css";
import floatingPopoverStyles from "@/components/ui/floatingPopover.module.css";

/** 材料選択セレクトの隣に置く情報アイコン(ⓘ)。選択中の材料の説明文
 * （backend/app/domain/material_catalog.py: MaterialSpec.description）をポップオーバーで
 * 表示する。材料が複数行並ぶ欄（terms/flags）でも行ごとに選択中の材料が違うため、
 * FieldLabelをそのまま流用せずラベル文言を持たない専用の小型トリガーにする（行ごとに
 * 毎回同じ文言を繰り返し表示すると煩雑なため）。 */
export function InfoPopoverButton({ ariaLabel, description }: { ariaLabel: string; description: string }) {
  return (
    <InfoPopover
      triggerClassName={infoButtonStyles.infoButton}
      triggerAriaLabel={ariaLabel}
      contentClassName={floatingPopoverStyles.floatingPopover}
    >
      {description}
    </InfoPopover>
  );
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
    <div className={styles.sectionLabelRow}>
      <p className={styles.groupLabel}>{label}</p>
      {description && <InfoPopoverButton ariaLabel={`${label}の説明`} description={description} />}
    </div>
  );
}

/** 素の<input type="number" value={n} onChange={e => onChange(Number(e.target.value))}>
 * は、「-」だけ入力した瞬間にNumber("-")===NaNとなり、Reactが管理するvalueがNaNへ
 * 倒れて入力済みの「-」ごと消える。同じ理由で末尾の小数点（"12."）も一時的に消える。
 * 入力中のDOM値はこのコンポーネント自身のローカル文字列stateにそのまま保持し、
 * 有限数としてパースできた時点でだけ親のonChangeへ伝える——「-」や「12.」のような
 * 未確定の中間状態を親のvalueへ反映しないことで、Reactに上書きされず最後まで
 * 打ち切れるようにする。外部起因でvalueが変わった場合（複製・既定値リセット等）は
 * ローカル文字列を追従させる——ただしuseEffectではなく「レンダー中に前回propsとの差分を
 * 見てstateを補正する」React公式推奨パターン（https://react.dev/learn/you-might-not-need-an-effect#adjusting-some-state-when-a-prop-changes）
 * を使う。useEffectで同期すると一度不正確な値でコミットしてから直後に描画し直す
 * 無駄な多重レンダーが発生する（react-hooks/set-state-in-effectが警告する箇所）ため。
 * onFocusで全選択にする（ワンタップで既存の値を全部選択して打ち直せる）。 */
export function NumberField({
  value,
  onChange,
  ...rest
}: {
  value: number;
  onChange: (next: number) => void;
} & Omit<React.InputHTMLAttributes<HTMLInputElement>, "value" | "onChange" | "type">) {
  const [text, setText] = useState(String(value));
  const [syncedValue, setSyncedValue] = useState(value);
  if (syncedValue !== value && Number(text) !== value) {
    setSyncedValue(value);
    setText(String(value));
  }
  return (
    <input
      type="number"
      value={text}
      onFocus={(e) => e.currentTarget.select()}
      onChange={(e) => {
        const raw = e.target.value;
        setText(raw);
        const parsed = Number(raw);
        if (raw.trim() !== "" && Number.isFinite(parsed)) onChange(parsed);
      }}
      {...rest}
    />
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
    <span className={styles.sliderNumberField}>
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
      <NumberField value={value} onChange={onChange} step="any" aria-label={label} />
    </span>
  );
}
