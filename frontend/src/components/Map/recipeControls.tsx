"use client";

import { useState } from "react";
import * as Popover from "@radix-ui/react-popover";
import Disclosure from "@/components/Disclosure/Disclosure";
import { InfoIcon } from "./icons";
import LayerChip from "./LayerChip";
import styles from "./recipeControls.module.css";

// 一般向けルート設定画面（RouteSettingsPanel）等が使う上書きUI部品
// （RecipePanelSection・withAutoEnable・FieldLabel）。

// 研究タブ各パネルの最上位の折りたたみ。MapLayersPanel.module.cssの.layerSection/
// .layerHeader/.layerTitle/.chevron/.layerBodyをcomposesでそのまま再利用し、地図側の
// レイヤー折りたたみと同一の見た目・挙動にする。ON/OFFチップも同じLayerChip部品を
// 流用（表示チップの「表示」→このチップは「上書き」）。
//
// 開閉（details）と有効/無効（チップ）は分離してある——両方を1つのチェックボックスが
// 兼ねると、値を確認するだけでも上書きを有効化する（＝地図やルート生成に即座に影響する）
// しかなくなるため。上書き無効中も中身は既定値で表示・編集でき、値を変更すると上書きが
// 自動でONになる（呼び出し側はonRecipeChange等をwithAutoEnableで包んで渡す）。
export function RecipePanelSection({
  title,
  overrideAriaLabel,
  overrideEnabled,
  onOverrideEnabledChange,
  children,
}: {
  title: string;
  /** LayerChipのariaLabel（例:「車の圧迫感のレシピを上書き」）。titleは`[...]`の
   * 補足文言を含むことがあるため、チップのアクセシブル名は別途渡す。 */
  overrideAriaLabel: string;
  overrideEnabled: boolean;
  onOverrideEnabledChange: (enabled: boolean) => void;
  children: React.ReactNode;
}) {
  return (
    <Disclosure
      className={styles.panelSection}
      headerClassName={styles.panelHeader}
      triggerClassName={styles.panelTitle}
      bodyClassName={styles.panelBody}
      summary={
        <>
          <span aria-hidden="true" className={styles.panelChevron} />
          {title}
        </>
      }
      // LayerChipはAccordion.Trigger（button）の兄弟として配置する（trailing）。
      // button内buttonという無効なHTMLを避けるため。
      trailing={
        <LayerChip
          label="上書き"
          ariaLabel={overrideAriaLabel}
          on={overrideEnabled}
          onClick={() => onOverrideEnabledChange(!overrideEnabled)}
        />
      }
    >
      {!overrideEnabled && (
        <p className={styles.panelOffHint}>上書きはOFFです[値を変更すると自動でONになります]</p>
      )}
      {children}
    </Disclosure>
  );
}

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
// に依存せず、開閉状態もこのコンポーネント自身が持つため呼び出し側は`description`を
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
  const [open, setOpen] = useState(false);
  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <span className={className ? `${styles.fieldLabel} ${className}` : styles.fieldLabel}>
        {hideLabel ? <span className="sr-only">{label}</span> : label}
        <Popover.Trigger asChild>
          <button
            type="button"
            className={styles.infoButton}
            aria-label={`${label}の説明を${open ? "隠す" : "表示"}`}
          >
            <InfoIcon />
          </button>
        </Popover.Trigger>
      </span>
      {/* Portalでdocument.body直下へ描画する（呼び出し側がoverflow-y:autoの
          サイドバー・BottomSheet内にあっても、その祖先要素のoverflowでクリップされない
          ようにするため）。 */}
      <Popover.Portal>
        <Popover.Content className={styles.infoTooltip} side="bottom" align="start" sideOffset={6}>
          {description}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
