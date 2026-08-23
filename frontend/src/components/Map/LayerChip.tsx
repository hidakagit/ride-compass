"use client";

import { Toggle } from "@radix-ui/react-toggle";
import type { LayerDataStatus } from "./mapLayers";
import { LAYER_DATA_STATUS_LABELS } from "./mapLayers";
import styles from "./LayerChip.module.css";

interface LayerChipProps {
  /** チップに表示するテキスト */
  label: string;
  on: boolean;
  disabled?: boolean;
  title?: string;
  /** 表示テキストと別のアクセシブル名が必要な場合（サイドバー側の「表示」チップ等）に指定 */
  ariaLabel?: string;
  /** レイヤーのデータ取得状態（改善計画T87）。表示ON時のみ小さな状態ドットを添える
   * （undefined＝正常。OFFやdisabled中はチップ自体の見た目でON/OFFが分かるため出さない）。 */
  dataStatus?: LayerDataStatus;
  /** イベントを受け取れる形にしているのは、<summary>内に置く場合にクリックが
   * 親のdetails開閉（ネイティブのデフォルト動作）へ伝播しないようpreventDefault/
   * stopPropagationする呼び出し側（MapLayersPanel）があるため。 */
  onClick: (event: React.MouseEvent<HTMLButtonElement>) => void;
}

// サイドバー（MapLayersPanel）の「表示」チップで使うテキストのみのON/OFFボタン。
// 以前は地図上（MapOverlayControls）とも共有していたが、地図上はスペース節約のため
// アイコン+短いラベルのボタン（MapOverlayControls.module.cssのiconChip）へ置き換えた。
//
// 押下状態の表示・キーボード操作（Space/Enter）はRadix Toggleへ委譲する（T253併用導入）。
// ただし押下状態自体は従来どおり呼び出し側（`on` prop）が完全に外部管理しており、
// このコンポーネントは内部状態を一切持たない（Toggleの`onPressedChange`は使わず生の
// `onClick`のみを渡す）。`<summary>`内で使う呼び出し側（RecipePanelSection等）が
// `event.preventDefault()`で親のdetails開閉を止めることがあるため、内部トグルロジックに
// 依存すると`composeEventHandlers`の仕様上（defaultPrevented時は内部ハンドラをスキップ）
// 押下が反映されないケースが生まれてしまう。生のonClickだけを使うことでこれを避ける。
export default function LayerChip({ label, on, disabled, title, ariaLabel, dataStatus, onClick }: LayerChipProps) {
  const active = on && !disabled;
  const showStatusDot = active && dataStatus != null;
  const statusLabel = dataStatus ? LAYER_DATA_STATUS_LABELS[dataStatus] : undefined;
  return (
    <Toggle
      pressed={active}
      aria-label={ariaLabel}
      disabled={disabled}
      onClick={onClick}
      className={active ? styles.chipActive : styles.chip}
      title={showStatusDot ? [title, statusLabel].filter(Boolean).join(" / ") : title}
    >
      {/* 状態→CSSクラスの対訳表をコンポーネント内に持たず、LayerDataStatusの値
          （"loading"/"empty"/"error"）とそろえたクラス名（LayerChip.module.css:
          statusDot_loading等）を直接組み立てて参照する（設計原則8）。 */}
      {showStatusDot && dataStatus && (
        <span aria-hidden="true" className={`${styles.statusDot} ${styles[`statusDot_${dataStatus}`]}`} />
      )}
      {label}
    </Toggle>
  );
}
