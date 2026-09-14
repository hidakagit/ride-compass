"use client";

import { Toggle } from "@radix-ui/react-toggle";
import styles from "./LayerChip.module.css";

interface LayerChipProps {
  /** チップに表示するテキスト */
  label: string;
  on: boolean;
  /** 表示テキストと別のアクセシブル名が必要な場合（サイドバー側の「表示」チップ等）に指定 */
  ariaLabel?: string;
  /** イベントを受け取れる形にしているのは、<summary>内に置く場合にクリックが
   * 親のdetails開閉（ネイティブのデフォルト動作）へ伝播しないようpreventDefault/
   * stopPropagationする呼び出し側があるため。 */
  onClick: (event: React.MouseEvent<HTMLButtonElement>) => void;
}

// ▶パネル（MapOverlayControls）の「表示」チップで使うテキストのみのON/OFFボタン。
// 地図上（MapOverlayControls）はスペース節約のためアイコン+短いラベルのボタン
// （MapOverlayControls.module.cssのiconChip）を使い、このコンポーネントは共有しない。
//
// 押下状態の表示・キーボード操作（Space/Enter）はRadix Toggleへ委譲する。ただし
// 押下状態自体は呼び出し側（`on` prop）が完全に外部管理しており、このコンポーネントは
// 内部状態を一切持たない（Toggleの`onPressedChange`は使わず生の`onClick`のみを渡す）。
// `<summary>`内で使う呼び出し側（`Disclosure`のtrailing等）が
// `event.preventDefault()`で親のdetails開閉を止めることがあるため、内部トグルロジックに
// 依存すると`composeEventHandlers`の仕様上（defaultPrevented時は内部ハンドラをスキップ）
// 押下が反映されないケースが生まれてしまう。生のonClickだけを使うことでこれを避ける。
export default function LayerChip({ label, on, ariaLabel, onClick }: LayerChipProps) {
  return (
    <Toggle pressed={on} aria-label={ariaLabel} onClick={onClick} className={on ? styles.chipActive : styles.chip}>
      {label}
    </Toggle>
  );
}
