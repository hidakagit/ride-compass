"use client";

import { useState } from "react";
import * as Popover from "@radix-ui/react-popover";
import Disclosure from "@/components/Disclosure/Disclosure";
import { InfoIcon } from "./icons";
import LayerChip from "./LayerChip";
import styles from "./recipeControls.module.css";

// 研究タブの評価重み上書きUI（WeightPanel）・一般向けルート設定画面（RouteSettingsPanel）
// が共有する上書きUI部品。T113でCarStressRecipePanel専用に実装したものを、2つ目のレシピ
// （当時の安全度レシピ。安全度軸自体はT148で削除済み）登場を機に汎用化した
// （改善計画: 安全度レシピ。「今後ほかの2次データのレシピが増えると思うので、くくり出して
// ほしい」というユーザー要望への対応）。改善計画T292: 車ストレス専用の3レシピパネル
// （CarStressRecipePanel等）の廃止に伴い、それらだけが使っていた部品（LevelPicker・
// AdjustmentStepper・CarClosenessReferenceSection・adjustmentEndpointColors・
// ScalarInput・ThresholdAdjustmentRow）は削除した。RecipePanelSection・withAutoEnable・
// FieldLabelは引き続きWeightPanel/RouteSettingsPanelが使う汎用部品として残す。

// 研究タブ各パネルの最上位の折りたたみ（改善計画: 研究タブのレイアウト改善。ユーザー
// フィードバック「地図の見え方のようなデザインに合わせて、折りたたみを工夫したり表示非表示を
// スマートにして」への対応）。MapLayersPanel.module.cssの.layerSection/.layerHeader/
// .layerTitle/.chevron/.layerBodyをcomposesでそのまま再利用し、地図側のレイヤー折りたたみと
// 同一の見た目・挙動にする。ON/OFFチップも同じLayerChip部品を流用（表示チップの「表示」→
// このチップは「上書き」）。
//
// 以前は「上書きする」チェックボックス1つが開閉と有効/無効を兼ねていたため、値を確認する
// だけでも上書きを有効化する（＝地図やルート生成に即座に影響する）しかなかった。
// MapLayersPanelの「OFF中でも絞り込み操作でき、操作すると自動でONになる」設計
// （handleRoadLegendToggle等）と同じ考え方で、開閉（details）と有効/無効（チップ）を分離する。
// 上書き無効中も中身は既定値で表示・編集でき、値を変更すると上書きが自動でONになる
// （呼び出し側はonRecipeChange等をwithAutoEnableで包んで渡す）。
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
      // button内buttonという無効なHTMLを避けるためで、以前<summary>内で必要だった
      // preventDefault/stopPropagation（開閉のデフォルト動作との衝突回避）は、
      // Trigger外に出たことで不要になった。
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
// フローティング表示する（T253併用導入。以前は呼び出し側がopen/onToggleを受け取り、
// DOM上input/tr等の後ろへ`<p>`/`<tr>`を個別に配置していたが、呼び出し側ごとに配置形が
// バラバラだった（div直後の<p> vs テーブル行内の<tr colSpan>）。Popoverはトリガー位置基準の
// フローティング表示のためDOM上の配置形に依存せず、開閉状態もこのコンポーネント自身が
// 持つため呼び出し側は`description`を渡すだけでよくなった）。`className`は任意の追加クラス
// （改善計画T118のモバイル幅溢れ修正: highway別基準値テーブル内では
// nowrap/flex-shrink:0を打ち消して折り返しを許可する必要があり、呼び出し側の
// module.cssでその上書きクラスを定義してここへ渡す）。

export function FieldLabel({
  label,
  description,
  className,
}: {
  label: string;
  description: string;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <span className={className ? `${styles.fieldLabel} ${className}` : styles.fieldLabel}>
        {label}
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
