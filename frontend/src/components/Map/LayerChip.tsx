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

// レイヤーON/OFFの唯一の操作部品。地図上（MapOverlayControls）とサイドバー
// （MapLayersPanel）の両方で同じ見た目・同じ挙動のこのチップを使うことで、
// 「どちらが本体か分からない別デザインのスイッチが2つある」状態を避ける
// （UI一貫性再編T30。以前はサイドバー側だけrole=switchのチェックボックスだった）。
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
