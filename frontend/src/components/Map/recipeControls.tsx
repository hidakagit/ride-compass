"use client";

import InfoPopover from "./InfoPopover";
import styles from "./recipeControls.module.css";

// 一般向けルート設定画面（RouteSettingsPanel）・軸スタジオが使う上書きUI部品。

// overrideEnabledがfalseの間に値が変更されたら、変更自体は伝えつつ上書きも自動で有効化する
// ラッパー（MapLayersPanel.tsxのhandleRoadLegendToggle等と同じ「操作したら自動でON」パターン）。
export function withAutoEnable<T>(
  overrideEnabled: boolean,
  onOverrideEnabledChange: (enabled: boolean) => void,
  setter: (next: T) => void,
): (next: T) => void {
  return (next) => {
    if (!overrideEnabled) onOverrideEnabledChange(true);
    setter(next);
  };
}

// フィールドラベル+情報アイコン。タップでも確実に開くクリック式の開閉ボタン
// （MapOverlayControlsのaria-expanded凡例トグルと同じ規約）。説明本体はRadix Popoverで
// フローティング表示する——トリガー位置基準のためDOM上の配置形（div直後 vs テーブル行内等）
// に依存しない。開閉状態は`InfoPopover`が持つため、呼び出し側は`description`を
// 渡すだけでよい。`className`は任意の追加クラス（highway別基準値テーブル内では
// nowrap/flex-shrink:0を打ち消して折り返しを許可する必要があり、呼び出し側の
// module.cssでその上書きクラスを定義してここへ渡す）。

export function FieldLabel({
  label,
  description,
  className,
  hideLabel,
}: {
  label: string;
  description: string;
  className?: string;
  /** trueの場合、ラベル文言はTailwindのsr-onlyで視覚的にのみ隠す（アイコン単体の見た目に
   * したい呼び出し側向け。aria-label自体はlabelの値のまま維持されるため読み上げは変わらない）。
   * ui/Dialog/Dialog.tsxのhideTitleと同じ既存パターン。 */
  hideLabel?: boolean;
}) {
  return (
    <InfoPopover
      triggerClassName={styles.infoButton}
      triggerAriaLabel={`${label}の説明`}
      contentClassName={styles.infoTooltip}
      label={label}
      labelClassName={className ? `${styles.fieldLabel} ${className}` : styles.fieldLabel}
      hideLabel={hideLabel}
    >
      {description}
    </InfoPopover>
  );
}
