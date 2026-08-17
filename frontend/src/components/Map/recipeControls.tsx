"use client";

import { InfoIcon } from "./icons";
import styles from "./recipeControls.module.css";

// レシピ入力フォーム（研究タブの各レシピパネル）共通のUI部品。T113でTrafficStressRecipePanel
// 専用に実装したものを、2つ目のレシピ（安全度レシピ）登場を機に汎用化した（改善計画:
// 安全度レシピ。「今後ほかの2次データのレシピが増えると思うので、くくり出してほしい」という
// ユーザー要望への対応）。段階数・色パレットは呼び出し側がpropsで渡すため、レシピごとの
// 段階数・配色差（例: 交通ストレスの緑〜赤、安全度のteal〜dark-red）はこのファイルの変更
// なしで吸収できる。

// 基準値のレベルピッカー。levelsぶんのボタンを並べ、選択値以下の段階をcolorsの色で塗って
// 進捗バー風に見せる。
export function LevelPicker({
  levels,
  colors,
  value,
  onChange,
  groupLabel,
}: {
  levels: number[];
  colors: Record<number, string>;
  value: number;
  onChange: (next: number) => void;
  groupLabel: string;
}) {
  return (
    <div className={styles.levelPicker} role="group" aria-label={groupLabel}>
      {levels.map((level) => (
        <button
          key={level}
          type="button"
          aria-pressed={value === level}
          aria-label={String(level)}
          data-filled={level <= value}
          className={styles.levelSegment}
          style={{ "--level-color": colors[level] } as React.CSSProperties}
          onClick={() => onChange(level)}
        >
          {level}
        </button>
      ))}
    </div>
  );
}

// 補正値のステッパー。-/+ボタン付きの数値入力欄。負値・正値に応じて呼び出し側が渡す色
// （地図の色分けの最低/最高段階から算出）で塗り、「0中心に変動する」ことを色だけで
// 確実に伝える（数値入力欄自体は残しているため直接タイプでの入力も引き続きできる）。
export function AdjustmentStepper({
  label,
  value,
  onChange,
  negativeColor,
  positiveColor,
}: {
  label: string;
  value: number;
  onChange: (next: number) => void;
  negativeColor: string;
  positiveColor: string;
}) {
  const color = value < 0 ? negativeColor : value > 0 ? positiveColor : undefined;
  return (
    <span className={styles.stepper}>
      <button
        type="button"
        className={styles.stepperButton}
        aria-label={`${label}を1減らす`}
        onClick={() => onChange(value - 1)}
      >
        −
      </button>
      <input
        type="number"
        step="1"
        aria-label={label}
        value={value}
        onChange={(e) => {
          const next = Number(e.target.value);
          if (Number.isNaN(next)) return;
          onChange(next);
        }}
        className={styles.stepperInput}
        style={color ? { background: color, borderColor: color, color: "#ffffff" } : undefined}
      />
      <button
        type="button"
        className={styles.stepperButton}
        aria-label={`${label}を1増やす`}
        onClick={() => onChange(value + 1)}
      >
        ＋
      </button>
    </span>
  );
}

// フィールドラベル+情報アイコン。タップでも確実に開くクリック式の開閉ボタン
// （MapOverlayControlsのaria-expanded凡例トグルと同じ規約）。説明本体（infoTooltip）は
// open/onToggleを渡す呼び出し側が、DOM上input/tr等の後ろへ別要素として配置する
// （このコンポーネント自身はラベル行だけを返す）。`className`は任意の追加クラス
// （改善計画T118のモバイル幅溢れ修正: highway別基準値テーブル内では
// nowrap/flex-shrink:0を打ち消して折り返しを許可する必要があり、呼び出し側の
// module.cssでその上書きクラスを定義してここへ渡す）。
export function FieldLabel({
  label,
  open,
  onToggle,
  className,
}: {
  label: string;
  open: boolean;
  onToggle: () => void;
  className?: string;
}) {
  return (
    <span className={className ? `${styles.fieldLabel} ${className}` : styles.fieldLabel}>
      {label}
      <button
        type="button"
        className={styles.infoButton}
        aria-expanded={open}
        aria-label={`${label}の説明を${open ? "隠す" : "表示"}`}
        onClick={onToggle}
      >
        <InfoIcon />
      </button>
    </span>
  );
}
