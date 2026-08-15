"use client";

import styles from "./LayerChip.module.css";

interface LayerChipProps {
  /** チップに表示するテキスト */
  label: string;
  on: boolean;
  disabled?: boolean;
  title?: string;
  /** 表示テキストと別のアクセシブル名が必要な場合（サイドバー側の「表示」チップ等）に指定 */
  ariaLabel?: string;
  /** イベントを受け取れる形にしているのは、<summary>内に置く場合にクリックが
   * 親のdetails開閉（ネイティブのデフォルト動作）へ伝播しないようpreventDefault/
   * stopPropagationする呼び出し側（MapLayersPanel）があるため。 */
  onClick: (event: React.MouseEvent<HTMLButtonElement>) => void;
}

// サイドバー（MapLayersPanel）の「表示」チップで使うテキストのみのON/OFFボタン。
// 以前は地図上（MapOverlayControls）とも共有していたが、地図上はスペース節約のため
// アイコン+短いラベルのボタン（MapOverlayControls.module.cssのiconChip）へ置き換えた。
export default function LayerChip({ label, on, disabled, title, ariaLabel, onClick }: LayerChipProps) {
  return (
    <button
      type="button"
      aria-pressed={on && !disabled}
      aria-label={ariaLabel}
      disabled={disabled}
      onClick={onClick}
      className={on && !disabled ? styles.chipActive : styles.chip}
      title={title}
    >
      {label}
    </button>
  );
}
